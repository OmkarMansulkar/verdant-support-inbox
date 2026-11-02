"""Calls the LLM (Groq's OpenAI-compatible chat API) for one draft.

Tries the primary model (openai/gpt-oss-120b in production), then the
fallback model (openai/gpt-oss-20b) once if the first attempt fails for any
reason: timeout, rate limit, provider error, or an answer that isn't the
shape we asked for. Each model has its own free-tier token budget, so the
fallback usually still works when the primary's daily budget is used up.
"""

import logging
import time
from dataclasses import dataclass

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import get_settings

log = logging.getLogger("app.llm")

TIMEOUT = httpx2.Timeout(20.0, connect=5.0)  # per attempt; at most two attempts
# gpt-oss models reason before answering, and that reasoning counts towards
# this limit. 1000 leaves room for low-effort reasoning plus a short reply,
# and still caps cost and runaway answers.
MAX_OUTPUT_TOKENS = 1000

# Strict structured output: the provider constrains generation so the answer
# must match this schema (Groq supports it for the gpt-oss models).
# Pydantic (DraftOutput) still re-checks it, including lengths.
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "draft_reply",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "needs_human": {"type": "boolean"},
                "flag_reason": {"type": ["string", "null"]},
            },
            "required": ["reply", "needs_human", "flag_reason"],
            "additionalProperties": False,
        },
    },
}

_client: httpx2.Client | None = None


class LlmError(Exception):
    """A short, readable reason, shown to the agent on a failed draft."""


class DraftOutput(BaseModel):
    """The JSON object the model must return."""
    model_config = ConfigDict(str_strip_whitespace=True)
    reply: str = Field(min_length=1, max_length=2000)
    needs_human: bool
    flag_reason: str | None = Field(default=None, max_length=300)


@dataclass
class DraftResult:
    reply: str
    needs_human: bool
    flag_reason: str | None
    model: str


def open_client() -> None:
    global _client
    _client = httpx2.Client(timeout=TIMEOUT)


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def draft_reply(messages: list[dict], draft_id: str | None = None) -> DraftResult:
    settings = get_settings()
    models = [settings.llm_model]
    if settings.llm_fallback_model != settings.llm_model:
        models.append(settings.llm_fallback_model)

    failures = []
    for model in models:
        started = time.monotonic()
        try:
            result = _call(model, messages)
        except LlmError as error:
            log.warning("llm_attempt_failed", extra={
                "draft_id": draft_id, "model": model, "reason": str(error),
                "duration_ms": round((time.monotonic() - started) * 1000),
            })
            failures.append(f"{model}: {error}")
            continue
        log.info("llm_attempt_succeeded", extra={
            "draft_id": draft_id, "model": model, "duration_ms": round((time.monotonic() - started) * 1000),
        })
        return result
    raise LlmError("; ".join(failures))


def _call(model: str, messages: list[dict]) -> DraftResult:
    if _client is None:
        raise RuntimeError("LLM client is not open")
    settings = get_settings()
    try:
        response = _client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,  # low: consistent, policy-faithful drafts
                "reasoning_effort": "low",  # a support reply needs little reasoning; keeps it fast and cheap
                "max_completion_tokens": MAX_OUTPUT_TOKENS,
                "response_format": RESPONSE_FORMAT,
            },
        )
    except httpx2.TimeoutException:
        raise LlmError("timed out")
    except httpx2.TransportError:
        raise LlmError("could not reach the LLM provider")

    if response.status_code == 429:
        raise LlmError("rate limit reached (429)")
    if response.status_code >= 400:
        # e.g. 401 bad key, 404 unknown or retired model, 400 output didn't fit the schema
        detail = _provider_message(response)
        raise LlmError(f"provider returned HTTP {response.status_code}" + (f": {detail}" if detail else ""))

    try:
        content = response.json()["choices"][0]["message"]["content"]
        output = DraftOutput.model_validate_json(content)
    except (ValueError, KeyError, IndexError, TypeError, ValidationError):
        raise LlmError("returned an answer in the wrong format")

    flag_reason = None
    if output.needs_human:
        # The agent should always see why; models occasionally flag without a reason.
        flag_reason = output.flag_reason or "Flagged by the AI (no reason given)"
    return DraftResult(output.reply, output.needs_human, flag_reason, model)


def _provider_message(response: httpx2.Response) -> str:
    """The provider's own error text (OpenAI format), shortened. A bare
    "HTTP 404" is hard to act on; "The model ... does not exist" is not."""
    try:
        return str(response.json()["error"]["message"])[:150]
    except (ValueError, KeyError, TypeError):
        return ""
