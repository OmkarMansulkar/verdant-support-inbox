import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app


def test_health_get():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_head():
    # Uptime monitors often use HEAD; it must not return 405.
    with TestClient(app) as client:
        response = client.head("/health")
    assert response.status_code == 200


def test_missing_variable_stops_startup(monkeypatch):
    config.get_settings.cache_clear()
    monkeypatch.delenv("GROQ_API_KEY")
    try:
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()
