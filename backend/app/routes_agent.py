"""Agent API: /api/agent/*. Every route requires a signed-in agent.

The auth dependency is attached to the router itself, not to each route, so a
route added later can't be left unprotected by accident (a test checks every
/api/agent route answers 401 without a token). Every query is filtered by the
agent's brand: another brand's conversation is a 404, not a 403, so ids from
other brands aren't even confirmed to exist.
"""

import logging
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app import db, drafts
from app.auth import Agent, current_agent
from app.ingest import make_preview
from app.webhook import reject_nul

log = logging.getLogger("app.agent")
router = APIRouter(prefix="/api/agent", dependencies=[Depends(current_agent)])

CurrentAgent = Annotated[Agent, Depends(current_agent)]  # same request: Supabase is asked only once

# Shared SQL: is this draft one the agent can retry? (failed, or pending and stale)
RETRYABLE_SQL = f"""(d.status = 'failed' or (d.status = 'pending'
    and d.updated_at < now() - interval '{drafts.STALE_AFTER_MINUTES} minutes'))"""


@router.get("/me")
def me(agent: CurrentAgent) -> dict:
    return {"display_name": agent.display_name, "brand_id": agent.brand_id}


@router.get("/conversations")
def list_conversations(agent: CurrentAgent) -> list[dict]:
    """The inbox: newest activity first, with the waiting draft's status so
    failed or flagged drafts stand out in the list."""
    with db.connection() as conn:
        return conn.execute(
            f"""
            select cv.id, c.name as customer_name, c.phone as customer_phone,
                   cv.last_message_preview, cv.last_message_at,
                   d.status as draft_status, coalesce(d.needs_human, false) as needs_human,
                   coalesce({RETRYABLE_SQL}, false) as draft_retryable
            from conversations cv
            join customers c on c.id = cv.customer_id
            left join drafts d on d.conversation_id = cv.id and d.status in ('pending', 'ready', 'failed')
            where cv.brand_id = %s and cv.status = 'open'
            order by cv.last_message_at desc
            limit 200
            """,
            (agent.brand_id,),
        ).fetchall()


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: UUID, agent: CurrentAgent) -> dict:
    """All messages in order, plus the draft waiting for review (if any)."""
    with db.connection() as conn:
        conversation = conn.execute(
            """
            select cv.id, cv.status, c.name as customer_name, c.phone as customer_phone,
                   c.external_id as customer_external_id
            from conversations cv join customers c on c.id = cv.customer_id
            where cv.id = %s and cv.brand_id = %s
            """,
            (conversation_id, agent.brand_id),
        ).fetchone()
        if conversation is None:
            raise HTTPException(404, "Conversation not found")
        messages = conn.execute(
            """
            select m.id, m.sender, m.body, m.created_at, a.display_name as agent_name
            from messages m left join agents a on a.user_id = m.agent_id
            where m.conversation_id = %s
            order by m.created_at, m.id
            """,
            (conversation_id,),
        ).fetchall()
        draft = conn.execute(
            f"""
            select d.id, d.status, d.body, d.needs_human, d.flag_reason, d.error, d.model,
                   d.attempts, d.message_id, d.updated_at, {RETRYABLE_SQL} as retryable
            from drafts d
            where d.conversation_id = %s and d.status in ('pending', 'ready', 'failed')
            """,
            (conversation_id,),
        ).fetchone()
    return {"conversation": conversation, "messages": messages, "draft": draft}


class ApproveIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    # The (possibly edited) reply. Length limit before the NUL check, so a too-long
    # reply gets Pydantic's normal "at most 4000 characters" message.
    text: Annotated[str, Field(min_length=1, max_length=4000), BeforeValidator(reject_nul)]


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: UUID, body: ApproveIn, agent: CurrentAgent) -> dict:
    """Save the agent's text as a reply and mark the draft used, in one transaction.

    The status check and the change are a single conditional UPDATE, so if two
    agents approve at the same moment exactly one wins; the other gets 409.
    A failed draft can be approved too: the agent types the reply themselves.
    """
    with db.connection() as conn:
        draft = conn.execute(
            """
            update drafts set status = 'approved', approved_by = %s, approved_at = now(), updated_at = now()
            where id = %s and brand_id = %s and status in ('ready', 'failed')
            returning conversation_id, body as ai_text
            """,
            (agent.user_id, draft_id, agent.brand_id),
        ).fetchone()
        if draft is None:
            conn.rollback()
            _explain_not_approvable(conn, draft_id, agent)

        reply = conn.execute(
            """
            insert into messages (brand_id, conversation_id, sender, body, agent_id, source_draft_id)
            values (%s, %s, 'agent', %s, %s, %s)
            returning id, sender, body, created_at
            """,
            (agent.brand_id, draft["conversation_id"], body.text, agent.user_id, draft_id),
        ).fetchone()
        conn.execute(
            "update conversations set last_message_at = now(), last_message_preview = %s where id = %s",
            (make_preview("Agent: " + body.text), draft["conversation_id"]),
        )

    log.info("draft_approved", extra={
        "draft_id": str(draft_id), "message_id": str(reply["id"]), "agent_id": agent.user_id,
        "edited": body.text != draft["ai_text"],  # how often agents change the AI's text
    })
    return {**reply, "agent_name": agent.display_name}


@router.post("/drafts/{draft_id}/retry", status_code=202)
def retry_draft(draft_id: UUID, agent: CurrentAgent, background_tasks: BackgroundTasks) -> dict:
    if not drafts.mark_for_retry(str(draft_id), agent.brand_id):
        raise HTTPException(409, "This draft can't be retried now: it's ready, approved, "
                                 "replaced by a newer one, or still being written")
    background_tasks.add_task(drafts.generate, str(draft_id))
    return {"status": "pending"}


def _explain_not_approvable(conn, draft_id: UUID, agent: Agent) -> NoReturn:
    """The approve didn't happen: say why, so the agent knows what to do next."""
    row = conn.execute(
        """
        select d.status, a.display_name as approved_by_name
        from drafts d left join agents a on a.user_id = d.approved_by
        where d.id = %s and d.brand_id = %s
        """,
        (draft_id, agent.brand_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Draft not found")
    reasons = {
        "approved": f"Already approved by {row['approved_by_name'] or 'another agent'}",
        "superseded": "The customer sent a newer message; review the new draft instead",
        "pending": "The AI is still writing this draft; try again in a moment",
    }
    raise HTTPException(409, reasons.get(row["status"], f"Draft is {row['status']}"))
