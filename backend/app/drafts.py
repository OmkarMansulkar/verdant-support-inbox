"""Generating AI drafts, after the webhook has already answered.

Draft states:
    pending -> ready | failed        (generate)
    failed / stale pending -> pending (retry)
    pending/ready/failed -> superseded (a newer customer message; see ingest.py)
    ready/failed -> approved          (agent approves; Phase 4)

Every change is a conditional UPDATE ("... where status = 'pending'"), so a
late writer becomes a no-op instead of overwriting newer state. Example: the
LLM is still writing draft A when a new customer message supersedes it;
A's result is then discarded rather than reviving a stale draft.
"""

import logging
import re
import time
from dataclasses import replace

from app import db, llm, prompt

log = logging.getLogger("app.drafts")

# A draft still pending after this long was lost (e.g. the server restarted
# mid-generation), since one generation takes at most ~45 s. Agents can retry it.
STALE_AFTER_MINUTES = 2

# Obvious attempts to instruct the AI. The prompt asks the model to flag these
# too, but in testing it sometimes answered correctly without flagging, and a
# security-relevant flag shouldn't depend on the model remembering. Subtler
# attempts are left to the model and to the agent's review.
INJECTION_PATTERN = re.compile(
    r"ignore\s+(all\s+|any\s+|the\s+|your\s+)?(previous\s+|prior\s+|above\s+|earlier\s+)?(instructions|rules|prompts?)\b"
    r"|^\s*(system|assistant|developer)\s*:"
    r"|system\s+prompt",
    re.IGNORECASE | re.MULTILINE,
)
INJECTION_FLAG = "Message contains instructions aimed at the AI"


def generate(draft_id: str) -> None:
    """Runs as a background task. Never raises: every outcome ends up in the
    draft's status (ready or failed, with a reason) and in the logs."""
    started = time.monotonic()
    try:
        context = _claim(draft_id)
        if context is None:
            log.info("draft_skipped_not_pending", extra={"draft_id": draft_id})
            return
        messages = prompt.build_messages(
            brand_name=context["brand_name"],
            knowledge_base=prompt.load_knowledge_base(context["brand_id"]),
            customer_name=context["customer_name"],
            history=context["history"],
        )
        # No database connection is held while waiting for the LLM.
        result = llm.draft_reply(messages, draft_id=draft_id)
        result = apply_safety_flags(result, context["history"])
        _save_result(draft_id, result, started)
    except llm.LlmError as error:
        _save_failure(draft_id, f"AI draft failed: {error}", started)
    except Exception:
        log.exception("draft_unexpected_error", extra={"draft_id": draft_id})
        _save_failure(draft_id, "AI draft failed: unexpected error (see server logs)", started)


def apply_safety_flags(result: llm.DraftResult, history: list[dict]) -> llm.DraftResult:
    """Force needs_human if a customer message the draft answers matches an
    obvious injection pattern. Keeps the model's own reason if it already flagged."""
    unanswered = []
    for message in reversed(history):  # customer messages since the last agent reply
        if message["sender"] != "customer":
            break
        unanswered.append(message["body"])
    if result.needs_human or not any(INJECTION_PATTERN.search(text) for text in unanswered):
        return result
    return replace(result, needs_human=True, flag_reason=INJECTION_FLAG)


def mark_for_retry(draft_id: str, brand_id: str) -> bool:
    """Put a failed (or stale pending) draft back to pending. Returns False if
    the draft isn't retryable, e.g. it was already retried, approved or
    superseded. The caller then schedules generate()."""
    with db.connection() as conn:
        updated = conn.execute(
            """
            update drafts set status = 'pending', error = null, updated_at = now()
            where id = %s and brand_id = %s
              and (status = 'failed'
                   or (status = 'pending' and updated_at < now() - make_interval(mins => %s)))
            """,
            (draft_id, brand_id, STALE_AFTER_MINUTES),
        ).rowcount
    if updated:
        log.info("draft_retry_requested", extra={"draft_id": draft_id})
    return updated == 1


def _claim(draft_id: str) -> dict | None:
    """Count the attempt and load what the prompt needs, if the draft is still pending."""
    with db.connection() as conn:
        draft = conn.execute(
            """
            update drafts set attempts = attempts + 1, updated_at = now()
            where id = %s and status = 'pending'
            returning conversation_id, brand_id
            """,
            (draft_id,),
        ).fetchone()
        if draft is None:
            return None
        names = conn.execute(
            """
            select b.name as brand_name, c.name as customer_name
            from conversations cv
            join customers c on c.id = cv.customer_id
            join brands b on b.id = cv.brand_id
            where cv.id = %s
            """,
            (draft["conversation_id"],),
        ).fetchone()
        recent = conn.execute(
            """
            select sender, body from messages
            where conversation_id = %s
            order by created_at desc, id desc
            limit %s
            """,
            (draft["conversation_id"], prompt.HISTORY_LENGTH),
        ).fetchall()
    return {
        "brand_id": draft["brand_id"],
        "brand_name": names["brand_name"],
        "customer_name": names["customer_name"],
        "history": list(reversed(recent)),  # oldest first
    }


def _save_result(draft_id: str, result: llm.DraftResult, started: float) -> None:
    with db.connection() as conn:
        updated = conn.execute(
            """
            update drafts
            set status = 'ready', body = %s, needs_human = %s, flag_reason = %s,
                model = %s, error = null, updated_at = now()
            where id = %s and status = 'pending'
            """,
            (result.reply, result.needs_human, result.flag_reason, result.model, draft_id),
        ).rowcount
    log_fields = {"draft_id": draft_id, "duration_ms": round((time.monotonic() - started) * 1000)}
    if updated:
        log.info("draft_ready", extra={**log_fields, "model": result.model, "needs_human": result.needs_human})
    else:
        log.info("draft_result_discarded", extra={**log_fields, "reason": "no longer pending (superseded)"})


def _save_failure(draft_id: str, reason: str, started: float) -> None:
    log_fields = {"draft_id": draft_id, "reason": reason, "duration_ms": round((time.monotonic() - started) * 1000)}
    try:
        with db.connection() as conn:
            conn.execute(
                "update drafts set status = 'failed', error = %s, updated_at = now() "
                "where id = %s and status = 'pending'",
                (reason, draft_id),
            )
        log.warning("draft_failed", extra=log_fields)
    except Exception:
        # Database down too: the draft stays pending, becomes stale after
        # STALE_AFTER_MINUTES, and the agent can retry it.
        log.exception("draft_failure_not_saved", extra=log_fields)
