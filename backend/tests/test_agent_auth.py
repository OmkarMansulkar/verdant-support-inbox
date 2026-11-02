"""Agent sign-in. Supabase Auth is replaced by a fake transport and the
agents-table lookup by a stub; the database-backed routes are exercised
against a real Postgres by the end-to-end check, not here."""

import httpx2
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import auth, routes_agent
from app.main import app

PRIYA = auth.Agent(user_id="11111111-1111-1111-1111-111111111111", brand_id="verdant-co", display_name="Priya")
SOME_UUID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def supabase(monkeypatch):
    """Fake Supabase Auth: 'good-token' belongs to Priya; other tokens are rejected.
    Set .down = True to simulate an outage."""
    class Fake:
        down = False
        status = 200
        calls = 0

    fake = Fake()

    def handler(request):
        fake.calls += 1
        if fake.down:
            raise httpx2.ConnectError("unreachable")
        if fake.status != 200:
            return httpx2.Response(fake.status, json={"msg": "error"})
        if request.headers["Authorization"] == "Bearer good-token":
            return httpx2.Response(200, json={"id": PRIYA.user_id, "email": "priya@example.com"})
        return httpx2.Response(401, json={"msg": "invalid JWT"})

    monkeypatch.setattr(auth, "open_client", lambda: None)  # keep the fake installed through startup
    monkeypatch.setattr(auth, "_client", httpx2.Client(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(auth, "_load_agent", lambda user_id: PRIYA if user_id == PRIYA.user_id else None)
    return fake


def agent_routes():
    """Every (method, path) on the agent router, with path parameters filled in.
    (Read from the router itself: since FastAPI 0.16x, app.routes holds a wrapper
    for included routers instead of a flat copy of their routes.)"""
    for route in routes_agent.router.routes:
        if isinstance(route, APIRoute):
            path = route.path.replace("{conversation_id}", SOME_UUID).replace("{draft_id}", SOME_UUID)
            for method in route.methods:
                yield method, path


def test_agent_routes_exist():
    assert len(list(agent_routes())) >= 5


@pytest.mark.parametrize("method, path", list(agent_routes()))
def test_every_agent_route_requires_sign_in(client, supabase, method, path):
    response = client.request(method, path, json={"text": "hi"})
    assert response.status_code == 401
    assert supabase.calls == 0  # rejected before asking Supabase


@pytest.mark.parametrize("header", ["Basic abc", "Bearer ", "good-token", "bearer good-token"])
def test_malformed_authorization_header_401(client, supabase, header):
    assert client.get("/api/agent/me", headers={"Authorization": header}).status_code == 401


def test_invalid_or_expired_token_401(client, supabase):
    response = client.get("/api/agent/me", headers={"Authorization": "Bearer expired-token"})
    assert response.status_code == 401
    assert "sign in again" in response.json()["detail"]


def test_signed_in_agent(client, supabase):
    response = client.get("/api/agent/me", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.json() == {"display_name": "Priya", "brand_id": "verdant-co"}
    assert supabase.calls == 1  # router-level and route-level dependency share one check


def test_signed_in_but_not_an_agent_403(client, supabase, monkeypatch):
    monkeypatch.setattr(auth, "_load_agent", lambda user_id: None)
    response = client.get("/api/agent/me", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 403


@pytest.mark.parametrize("problem", ["down", 500])
def test_auth_outage_is_503_not_401(client, supabase, problem):
    # An outage must not look like "your session expired" and sign agents out.
    if problem == "down":
        supabase.down = True
    else:
        supabase.status = problem
    response = client.get("/api/agent/me", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 503


def test_bad_ids_are_422(client, supabase):
    headers = {"Authorization": "Bearer good-token"}
    assert client.get("/api/agent/conversations/not-a-uuid", headers=headers).status_code == 422
    assert client.post("/api/agent/drafts/123/approve", json={"text": "hi"}, headers=headers).status_code == 422


@pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": "   "}, {"text": "x" * 4001}, {"text": "a\u0000b"}])
def test_approve_text_is_validated(client, supabase, payload):
    response = client.post(f"/api/agent/drafts/{SOME_UUID}/approve", json=payload,
                           headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 422
