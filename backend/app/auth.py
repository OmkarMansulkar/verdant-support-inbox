"""Who is calling the agent API?

The frontend signs in with Supabase Auth and sends the session token as
`Authorization: Bearer <token>`. For each request we:
  1. ask Supabase whose token it is (GET /auth/v1/user)  -> 401 if invalid or expired
  2. look that user up in our agents table              -> 403 if not an agent
Signing in proves who you are; the agents row is what makes you an agent,
and for which brand.

If Supabase Auth can't be reached we answer 503, not 401: an outage
shouldn't look like "your session expired" and sign every agent out.
"""

import logging
from dataclasses import dataclass

import httpx2
from fastapi import Header, HTTPException

from app import db
from app.config import get_settings

log = logging.getLogger("app.auth")

_client: httpx2.Client | None = None


@dataclass(frozen=True)
class Agent:
    user_id: str
    brand_id: str
    display_name: str


def open_client() -> None:
    global _client
    _client = httpx2.Client(timeout=httpx2.Timeout(5.0))


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def current_agent(authorization: str | None = Header(default=None)) -> Agent:
    """FastAPI dependency: the signed-in agent, or an HTTP error."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not authorization or not authorization.startswith("Bearer ") or not token:
        raise HTTPException(401, "Sign in required")

    user_id = _verify_token(token)
    agent = _load_agent(user_id)
    if agent is None:
        log.warning("agent_access_denied", extra={"user_id": user_id, "reason": "not an agent"})
        raise HTTPException(403, "This account is not a support agent")
    return agent


def _verify_token(token: str) -> str:
    """Supabase's answer for this token: the user's id, or an HTTP error."""
    if _client is None:
        raise RuntimeError("Auth client is not open")
    settings = get_settings()
    try:
        response = _client.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key},
        )
    except httpx2.HTTPError:
        log.exception("auth_provider_unreachable")
        raise HTTPException(503, "Sign-in service unavailable, please try again")

    if response.status_code in (401, 403):
        raise HTTPException(401, "Session expired or invalid, please sign in again")
    if response.status_code != 200:
        log.error("auth_provider_error", extra={"status": response.status_code})
        raise HTTPException(503, "Sign-in service unavailable, please try again")
    try:
        return str(response.json()["id"])
    except (ValueError, KeyError, TypeError):
        log.error("auth_provider_bad_response")
        raise HTTPException(503, "Sign-in service unavailable, please try again")


def _load_agent(user_id: str) -> Agent | None:
    with db.connection() as conn:
        row = conn.execute(
            "select user_id, brand_id, display_name from agents where user_id = %s",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return Agent(user_id=str(row["user_id"]), brand_id=row["brand_id"], display_name=row["display_name"])
