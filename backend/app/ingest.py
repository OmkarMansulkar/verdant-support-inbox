"""Saving one customer message: a single database transaction.

Steps (all or nothing):
  1. upsert the customer (latest name/phone wins)
  2. get or create their open conversation and bump its latest activity
  3. insert the message; if it's a duplicate, roll everything back
  4. supersede the conversation's previous active draft, if any
  5. create a pending draft for this message (drafted after the response)

Steps 1 and 2 lock the customer's rows until commit, so two messages from
the same customer arriving at once are saved one after the other, never
interleaved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app import db

if TYPE_CHECKING:
    from app.webhook import WebhookEvent

PREVIEW_LENGTH = 120


class UnknownBrand(Exception):
    pass


@dataclass
class StoredMessage:
    message_id: str
    conversation_id: str
    draft_id: str
    superseded_drafts: int


def save_customer_message(event: WebhookEvent) -> StoredMessage | None:
    """Returns None if this message was already stored (a retried delivery)."""
    text = event.message.text
    with db.connection() as conn:
        brand = conn.execute("select id from brands where id = %s", (event.brand_id,)).fetchone()
        if brand is None:
            raise UnknownBrand(event.brand_id)

        customer = conn.execute(
            """
            insert into customers (brand_id, external_id, name, phone)
            values (%s, %s, %s, %s)
            on conflict (brand_id, external_id)
              do update set name = excluded.name, phone = excluded.phone
            returning id
            """,
            (event.brand_id, event.customer.id, event.customer.name, event.customer.phone),
        ).fetchone()

        # The partial unique index allows one open conversation per customer.
        # "do update" also locks that row until commit.
        conversation = conn.execute(
            """
            insert into conversations (brand_id, customer_id, last_message_preview)
            values (%s, %s, %s)
            on conflict (customer_id) where status = 'open'
              do update set last_message_at = now(),
                            last_message_preview = excluded.last_message_preview
            returning id
            """,
            (event.brand_id, customer["id"], _preview(text)),
        ).fetchone()

        # Unique (brand_id, event_id) and (brand_id, external_id): a retry of
        # the same event, or the same message re-sent under a new event id,
        # inserts nothing and returns no row.
        message = conn.execute(
            """
            insert into messages (brand_id, conversation_id, sender, body, event_id, external_id, sent_at)
            values (%s, %s, 'customer', %s, %s, %s, %s)
            on conflict do nothing
            returning id
            """,
            (event.brand_id, conversation["id"], text, event.event_id, event.message.id, event.timestamp),
        ).fetchone()
        if message is None:
            conn.rollback()  # undo the customer/conversation updates above
            return None

        # The agent answers the latest message, with the whole thread as context,
        # so an older draft still waiting for review is replaced.
        superseded = conn.execute(
            """
            update drafts set status = 'superseded', updated_at = now()
            where conversation_id = %s and status in ('pending', 'ready', 'failed')
            """,
            (conversation["id"],),
        ).rowcount

        draft = conn.execute(
            """
            insert into drafts (brand_id, conversation_id, message_id)
            values (%s, %s, %s)
            returning id
            """,
            (event.brand_id, conversation["id"], message["id"]),
        ).fetchone()

    return StoredMessage(
        message_id=str(message["id"]),
        conversation_id=str(conversation["id"]),
        draft_id=str(draft["id"]),
        superseded_drafts=superseded,
    )


def _preview(text: str) -> str:
    """One line for the inbox list: whitespace collapsed, cut at PREVIEW_LENGTH."""
    one_line = re.sub(r"\s+", " ", text).strip()
    if len(one_line) <= PREVIEW_LENGTH:
        return one_line
    return one_line[: PREVIEW_LENGTH - 1].rstrip() + "…"
