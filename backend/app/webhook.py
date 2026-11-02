"""Incoming customer messages: POST /webhook.

Checks run in this order, cheapest and most important first:
  1. body size     -> 413   (read with a cap, before anything else)
  2. signature     -> 401   (HMAC of the raw bytes; nothing is parsed before this)
  3. JSON syntax   -> 400
  4. schema        -> 422   (field errors listed; input values never echoed back)
  5. store         -> 200   accepted | duplicate | ignored
handle_webhook() is also what the Customer view calls (Phase 6), so both
paths share every one of these steps.
"""

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import AwareDatetime, BeforeValidator, BaseModel, ConfigDict, Field, ValidationError

from app import ingest
from app.config import get_settings

log = logging.getLogger("app.webhook")
router = APIRouter()

MAX_BODY_BYTES = 64 * 1024
SIGNATURE_PREFIX = "sha256="


# ---------- 1. Body size ----------

async def read_limited_body(request: Request) -> bytes:
    """Read the raw body, refusing anything over MAX_BODY_BYTES.

    Reads chunk by chunk, so a sender that lies about (or omits)
    Content-Length still can't make us hold a huge body in memory.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _reject(413, "body_too_large", "Request body is larger than 64 KB")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise _reject(413, "body_too_large", "Request body is larger than 64 KB")
    return bytes(body)


# ---------- 2. Signature ----------

def sign(raw_body: bytes, secret: str) -> str:
    """The X-Signature header value for a body: 'sha256=<hex HMAC-SHA256>'."""
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return SIGNATURE_PREFIX + digest


def signature_is_valid(raw_body: bytes, header_value: str | None, secret: str) -> bool:
    if not header_value or not header_value.startswith(SIGNATURE_PREFIX):
        return False
    provided = header_value.removeprefix(SIGNATURE_PREFIX).strip().lower()
    if not provided.isascii():  # compare_digest only accepts ASCII strings
        return False
    expected = sign(raw_body, secret).removeprefix(SIGNATURE_PREFIX)
    # Constant time: how long the comparison takes doesn't reveal how many
    # leading characters of a forged signature were right.
    return hmac.compare_digest(expected, provided)


# ---------- 3–4. Payload models ----------

def _no_nul(value):
    # Valid JSON can contain \u0000, but Postgres text can't store it; without
    # this check such a message would crash the insert with a 500.
    # Runs before the normal string checks (non-strings are left to those).
    if isinstance(value, str) and "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


Text = Annotated[str, BeforeValidator(_no_nul)]


class _Model(BaseModel):
    # Unknown extra fields are ignored, so the sender can add fields later
    # without breaking us. Surrounding whitespace is stripped.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Envelope(_Model):
    """The fields every event has. Checked first, so an event type we don't
    handle can be acknowledged without requiring a message body."""
    event_id: Text = Field(min_length=1, max_length=100)
    type: Text = Field(min_length=1, max_length=50)
    brand_id: Text = Field(min_length=1, max_length=50)


class CustomerIn(_Model):
    id: Text = Field(min_length=1, max_length=100)
    name: Text = Field(min_length=1, max_length=200)
    phone: Text = Field(min_length=3, max_length=32)


class MessageIn(_Model):
    id: Text = Field(min_length=1, max_length=100)
    type: Text = Field(min_length=1, max_length=50)
    # Optional here because non-text messages (images) have no text; for
    # "text" messages handle_webhook requires it to be non-empty.
    text: Annotated[str, Field(max_length=4000), BeforeValidator(_no_nul)] | None = None  # same limit as the database


class WebhookEvent(Envelope):
    type: Literal["message.received"]
    timestamp: AwareDatetime  # must include a timezone, e.g. ...Z
    customer: CustomerIn
    message: MessageIn


# ---------- 5. Handling ----------

@dataclass
class Outcome:
    status: Literal["accepted", "duplicate", "ignored"]
    event_id: str
    message_id: str | None = None   # our id for the stored message
    draft_id: str | None = None     # the pending draft to generate (Phase 3)
    reason: str | None = None       # why an event was ignored

    def response(self) -> dict:
        body = {"status": self.status, "event_id": self.event_id}
        if self.message_id:
            body["message_id"] = self.message_id
        if self.reason:
            body["reason"] = self.reason
        return body


def handle_webhook(raw_body: bytes, signature: str | None) -> Outcome:
    started = time.monotonic()

    if not signature_is_valid(raw_body, signature, get_settings().webhook_secret):
        reason = "missing_signature" if not signature else "bad_signature"
        raise _reject(401, reason, "Missing or invalid X-Signature header")

    try:
        payload = json.loads(raw_body)
    except (ValueError, RecursionError):  # bad JSON, bad UTF-8, or absurdly deep nesting
        raise _reject(400, "invalid_json", "Body is not valid JSON")

    envelope = _validate(Envelope, payload, event_id=None)
    if envelope.type != "message.received":
        return _ignored(envelope.event_id, f"unsupported event type '{envelope.type}'")

    event = _validate(WebhookEvent, payload, event_id=envelope.event_id)
    if event.message.type != "text":
        return _ignored(event.event_id, f"unsupported message type '{event.message.type}'")
    if not event.message.text:
        raise _reject(422, "invalid_payload",
                      [{"field": "message.text", "problem": "required for text messages"}],
                      event_id=event.event_id)

    try:
        stored = ingest.save_customer_message(event)
    except ingest.UnknownBrand:
        raise _reject(422, "unknown_brand", [{"field": "brand_id", "problem": "unknown brand"}],
                      event_id=event.event_id)
    except Exception:
        # Database down, pool exhausted, a bug: a 5xx tells the sender to retry later.
        log.exception("webhook_store_failed", extra={"event_id": event.event_id})
        raise HTTPException(503, "Could not store the message right now; please retry")

    log_fields = {
        "event_id": event.event_id,
        "external_message_id": event.message.id,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
    if stored is None:
        log.info("webhook_duplicate", extra=log_fields)
        return Outcome("duplicate", event.event_id)

    # Ids only, never the text: customer messages are personal data.
    log.info("message_stored", extra={
        **log_fields,
        "message_id": stored.message_id,
        "conversation_id": stored.conversation_id,
        "draft_id": stored.draft_id,
        "superseded_drafts": stored.superseded_drafts,
        "text_length": len(event.message.text),
    })
    return Outcome("accepted", event.event_id, message_id=stored.message_id, draft_id=stored.draft_id)


def _validate(model, data, event_id: str | None):
    try:
        return model.model_validate(data)
    except ValidationError as error:
        # List which fields are wrong and why, but not the values sent:
        # they can be long, and they're customer data.
        problems = [
            {"field": ".".join(str(part) for part in e["loc"]) or "(body)", "problem": e["msg"]}
            for e in error.errors(include_input=False, include_url=False)
        ]
        raise _reject(422, "invalid_payload", problems, event_id=event_id)


def _ignored(event_id: str, reason: str) -> Outcome:
    # Acknowledged with 200 so the sender doesn't keep retrying something we chose to skip.
    log.info("webhook_ignored", extra={"event_id": event_id, "reason": reason})
    return Outcome("ignored", event_id, reason=reason)


def _reject(status: int, reason: str, detail, event_id: str | None = None) -> HTTPException:
    log.warning("webhook_rejected", extra={"status": status, "reason": reason, "event_id": event_id})
    return HTTPException(status, detail)


# ---------- Route ----------

@router.post("/webhook")
def receive_webhook(
    raw_body: bytes = Depends(read_limited_body),
    x_signature: str | None = Header(default=None),
) -> dict:
    # The body arrives as raw bytes (not a Pydantic parameter) because the
    # signature must be checked on exactly the bytes that were sent.
    outcome = handle_webhook(raw_body, x_signature)
    # Phase 3: schedule AI drafting for outcome.draft_id as a background task.
    return outcome.response()
