"""Customer view API: same code path as the webhook, identities, limits, no drafts.
The database is faked; the real transaction is exercised against a running server."""

import re
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, drafts, ingest, rate_limit, routes_customer, webhook
from app.main import app


@pytest.fixture
def stored(monkeypatch):
    """Fake ingest with real idempotency on event_id: records what it was given."""
    events, seen = [], set()

    def fake_save(event):
        if event.event_id in seen:
            return None
        seen.add(event.event_id)
        events.append(event)
        return ingest.StoredMessage("m-1", "c-1", "d-1", superseded_drafts=0)

    monkeypatch.setattr(ingest, "save_customer_message", fake_save)
    return events


@pytest.fixture(autouse=True)
def scheduled_drafts(monkeypatch):
    calls = []
    monkeypatch.setattr(drafts, "generate", lambda draft_id: calls.append(draft_id))
    return calls


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    for limiter in (routes_customer.send_limiter, routes_customer.read_limiter):
        limiter._hits.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def send(client, headers=None, **fields):
    body = {"client_message_id": str(uuid.uuid4()), "test_customer_id": "cust_1042",
            "text": "What is your return policy?", **fields}
    body = {key: value for key, value in body.items() if value is not None}
    return client.post("/api/customer/messages", json=body, headers=headers or {})


# ---------- same path as the webhook ----------

def test_send_goes_through_signature_check_and_schedules_draft(client, stored, scheduled_drafts, monkeypatch):
    checked = []
    real_check = webhook.signature_is_valid

    def spy(raw_body, header, secret):
        result = real_check(raw_body, header, secret)
        checked.append(result)
        return result

    monkeypatch.setattr(webhook, "signature_is_valid", spy)
    message_id = uuid.uuid4()
    response = send(client, client_message_id=str(message_id))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "customer_id": "cust_1042"}
    assert checked == [True]  # the webhook's own signature check ran, and passed
    event = stored[0]
    assert event.event_id == f"web_evt_{message_id}"
    assert event.message.id == f"web_msg_{message_id}"
    assert event.brand_id == "verdant-co"
    assert event.timestamp.tzinfo is not None
    assert scheduled_drafts == ["d-1"]


def test_same_client_message_id_twice_is_a_duplicate(client, stored, scheduled_drafts):
    message_id = str(uuid.uuid4())
    assert send(client, client_message_id=message_id).json()["status"] == "accepted"
    assert send(client, client_message_id=message_id).json()["status"] == "duplicate"
    assert len(stored) == 1
    assert scheduled_drafts == ["d-1"]  # one draft, not two


# ---------- who the customer is ----------

def test_test_customer_identity_comes_from_the_server(client, stored):
    # A name sent alongside a test customer id is ignored: the public endpoint
    # can't rename Aisha.
    send(client, name="Mallory", phone="+10000000000")
    assert stored[0].customer.model_dump() == {"id": "cust_1042", "name": "Aisha Khan", "phone": "+919800000001"}


def test_typed_customer_keyed_by_phone_digits(client, stored):
    first = send(client, test_customer_id=None, name="Kabir Shah", phone="+91 98000-00004")
    second = send(client, test_customer_id=None, name="Kabir Shah", phone="+919800000004")
    assert first.json()["customer_id"] == second.json()["customer_id"] == "web_919800000004"
    assert stored[0].customer.phone == "+919800000004"


@pytest.mark.parametrize("fields, status", [
    ({"test_customer_id": "cust_9999"}, 422),                                  # not a test customer
    ({"test_customer_id": None, "name": "Kabir", "phone": "12345"}, 422),      # too few digits
    ({"test_customer_id": None, "name": "Kabir", "phone": "+91 98OOO 00004"}, 422),  # letters
    ({"test_customer_id": None, "phone": "+919800000004"}, 422),               # no name
    ({"text": "   "}, 422),                                                    # whitespace only
    ({"text": "x" * 4001}, 422),
    ({"text": "hi\u0000there"}, 422),
    ({"client_message_id": "not-a-uuid"}, 422),
    ({"is_admin": True}, 422),                                                 # unknown field
])
def test_bad_input_rejected_and_nothing_stored(client, stored, fields, status):
    assert send(client, **fields).status_code == status
    assert stored == []


def test_body_over_64kb_413(client, stored):
    assert send(client, text="x" * 70_000).status_code == 413


def test_test_customers_match_seed_sql(client):
    seed = (Path(__file__).parent.parent / "seed.sql").read_text()
    seeded = re.findall(r"\('verdant-co', '(cust_\d+)', '([^']+)',\s*'(\+\d+)'\)", seed)
    listed = client.get("/api/customer/test-customers").json()
    assert [(c["id"], c["name"], c["phone"]) for c in listed] == seeded


# ---------- reading: messages only, never drafts ----------

@pytest.fixture
def fake_db(monkeypatch):
    queries = []
    rows = [
        {"id": "m-1", "sender": "customer", "body": "Hello", "created_at": "2026-11-03T10:00:00Z"},
        {"id": "m-2", "sender": "agent", "body": "Hi Aisha!", "created_at": "2026-11-03T10:05:00Z"},
    ]

    class Result:
        def fetchall(self):
            return rows

    class Conn:
        def execute(self, sql, params):
            queries.append((sql, params))
            return Result()

    @contextmanager
    def connection():
        yield Conn()

    monkeypatch.setattr(db, "connection", connection)
    return queries


def test_conversation_reads_only_messages(client, fake_db):
    response = client.get("/api/customer/conversation", params={"test_customer_id": "cust_1042"})
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == "cust_1042"
    assert [set(m) for m in body["messages"]] == [{"id", "sender", "body", "created_at"}] * 2
    sql, params = fake_db[0]
    assert "draft" not in sql.lower()
    assert params == ("verdant-co", "cust_1042")


def test_conversation_by_phone_uses_the_same_key_as_sending(client, fake_db):
    client.get("/api/customer/conversation", params={"phone": "+91 98000 00004"})
    assert fake_db[0][1] == ("verdant-co", "web_919800000004")


def test_conversation_needs_a_customer(client, fake_db):
    assert client.get("/api/customer/conversation").status_code == 422
    assert client.get("/api/customer/conversation", params={"test_customer_id": "x"}).status_code == 422
    assert fake_db == []


# ---------- rate limits ----------

def test_eleventh_message_in_a_minute_is_429(client, stored):
    for _ in range(10):
        assert send(client).status_code == 200
    response = send(client)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert len(stored) == 10


def test_limit_is_per_client_ip(client, stored):
    for _ in range(10):
        send(client, headers={"True-Client-IP": "203.0.113.1"})
    assert send(client, headers={"True-Client-IP": "203.0.113.1"}).status_code == 429
    assert send(client, headers={"True-Client-IP": "203.0.113.2"}).status_code == 200


def test_forged_x_forwarded_for_does_not_reset_the_limit(client, stored):
    for i in range(10):
        send(client, headers={"X-Forwarded-For": f"198.51.100.{i}"})
    assert send(client, headers={"X-Forwarded-For": "198.51.100.99"}).status_code == 429


def test_window_slides(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = rate_limit.RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    now[0] += 61
    assert limiter.allow("a")


def test_quiet_clients_are_forgotten(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(rate_limit, "MAX_TRACKED_CLIENTS", 3)
    limiter = rate_limit.RateLimiter(max_requests=5, window_seconds=60)
    for key in "abc":
        limiter.allow(key)
    now[0] += 61
    limiter.allow("d")  # 4 tracked > 3: the quiet a, b, c are dropped
    assert set(limiter._hits) == {"d"}
