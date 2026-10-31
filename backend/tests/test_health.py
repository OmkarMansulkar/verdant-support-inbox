import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app


def test_health_ok(monkeypatch):
    monkeypatch.setattr(db, "is_healthy", lambda: True)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_head(monkeypatch):
    # Uptime monitors often use HEAD; it must not return 405.
    monkeypatch.setattr(db, "is_healthy", lambda: True)
    with TestClient(app) as client:
        response = client.head("/health")
    assert response.status_code == 200


def test_health_reports_database_down(monkeypatch):
    # 503 makes the uptime monitor alert on database outages too.
    monkeypatch.setattr(db, "is_healthy", lambda: False)
    with TestClient(app) as client:
        get_response = client.get("/health")
        head_response = client.head("/health")
    assert get_response.status_code == 503
    assert get_response.json() == {"status": "error", "database": "unreachable"}
    assert head_response.status_code == 503


def test_missing_variable_stops_startup(monkeypatch):
    config.get_settings.cache_clear()
    monkeypatch.delenv("GROQ_API_KEY")
    try:
        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()
