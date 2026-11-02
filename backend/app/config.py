"""Settings, read once from environment variables.

If any required variable is missing, the app refuses to start and lists the
missing names, so a bad deploy fails at deploy time instead of at 2 a.m.
"""

import os
import re
from dataclasses import dataclass
from functools import lru_cache

REQUIRED_VARIABLES = [
    "DATABASE_URL",
    "WEBHOOK_SECRET",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "GROQ_API_KEY",
    "LLM_MODEL",
    "LLM_FALLBACK_MODEL",
    "CORS_ORIGINS",
]


PLACEHOLDER = re.compile(r"<[a-z0-9-]+>")  # the style used in .env.example


@dataclass(frozen=True)
class Settings:
    database_url: str
    webhook_secret: str
    supabase_url: str
    supabase_anon_key: str
    groq_api_key: str
    llm_model: str
    llm_fallback_model: str
    cors_origins: list[str]
    llm_base_url: str  # optional; any OpenAI-compatible provider works


@lru_cache
def get_settings() -> Settings:
    missing = [name for name in REQUIRED_VARIABLES if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    # A value copied from .env.example but never filled in (e.g. "<groq-api-key>")
    # is present but useless; it would only fail at the first real call.
    placeholders = [name for name in REQUIRED_VARIABLES if PLACEHOLDER.search(os.environ[name])]
    if placeholders:
        raise RuntimeError(
            f"Environment variables still contain a <placeholder> from .env.example: {', '.join(placeholders)}"
        )

    env = os.environ
    return Settings(
        database_url=env["DATABASE_URL"].strip(),
        webhook_secret=env["WEBHOOK_SECRET"].strip(),
        supabase_url=env["SUPABASE_URL"].strip().rstrip("/"),
        supabase_anon_key=env["SUPABASE_ANON_KEY"].strip(),
        groq_api_key=env["GROQ_API_KEY"].strip(),
        llm_model=env["LLM_MODEL"].strip(),
        llm_fallback_model=env["LLM_FALLBACK_MODEL"].strip(),
        cors_origins=[
            origin.strip().rstrip("/")
            for origin in env["CORS_ORIGINS"].split(",")
            if origin.strip()
        ],
        llm_base_url=env.get("LLM_BASE_URL", "").strip().rstrip("/") or "https://api.groq.com/openai/v1",
    )
