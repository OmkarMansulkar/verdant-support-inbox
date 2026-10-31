"""Tests never need real secrets or a real database.

Harmless env values are set before the app is imported, and the connection
pool is replaced with a no-op so the app starts without Postgres.
"""

import os

import pytest

TEST_ENV = {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "WEBHOOK_SECRET": "test-secret",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "GROQ_API_KEY": "test-groq-key",
    "LLM_MODEL": "test-model",
    "LLM_FALLBACK_MODEL": "test-fallback-model",
    "CORS_ORIGINS": "http://localhost:5173",
}

os.environ.update(TEST_ENV)


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    from app import db

    monkeypatch.setattr(db, "open_pool", lambda database_url: None)
    monkeypatch.setattr(db, "close_pool", lambda: None)
