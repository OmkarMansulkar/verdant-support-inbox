"""Tests never need real secrets: set harmless values before the app is imported."""

import os

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
