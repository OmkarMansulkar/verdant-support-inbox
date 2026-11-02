"""Webhook: signature, validation and status codes. The database is faked;
the real ingest transaction is exercised by scripts/run_test_cases.py."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from app import ingest
from app.main import app
from app.webhook import sign, signature_is_valid

SECRET = "test-secret"  # matches tests/conftest.py

SAMPLE = {
    "event_id": "evt_7f3a91c2",
    "type": "message.received",
    "brand_id": "verdant-co",
    "timestamp": "2026-11-03T10:15:22Z",
    "customer": {"id": "cust_1042", "name": "Aisha Khan", "phone": "+919800000001"},
    "message": {
        "id": "msg_88213",
        "type": "text",
        "text": "Hi, my order #4471 hasn't arrived yet. Can I change the delivery address?",
    },
}


@pytest.fixture
def stored(monkeypatch):
    """Fake ingest: records what it was given and pretends to store it."""
    calls = []

    def fake_save(event):
        calls.append(event)
        return ingest.StoredMessage("m-1", "c-1", "d-1", superseded_drafts=0)

    monkeypatch.setattr(ingest, "save_customer_message", fake_save)
    return calls


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def post(client, body, signature="auto"):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Signature"] = sign(raw, SECRET)
    elif signature is not None:
        headers["X-Signature"] = signature
    return client.post("/webhook", content=raw, headers=headers)


def with_changes(**changes):
    payload = copy.deepcopy(SAMPLE)
    for dotted, value in changes.items():
        target = payload
        *parents, last = dotted.split("__")
        for key in parents:
            target = target[key]
        if value is DELETE:
            del target[last]
        else:
            target[last] = value
    return payload


DELETE = object()


# ---------- signature ----------

def test_signature_round_trip():
    raw = b'{"a": 1}'
    assert signature_is_valid(raw, sign(raw, SECRET), SECRET)


def test_signature_hex_is_case_insensitive():
    raw = b'{"a": 1}'
    upper = "sha256=" + sign(raw, SECRET).removeprefix("sha256=").upper()
    assert signature_is_valid(raw, upper, SECRET)


@pytest.mark.parametrize("header", [
    None, "", "sha256=", "sha256=deadbeef", "md5=abc",
    "sha256=" + "0" * 64, "sha256=ünïcode",
])
def test_bad_signatures_rejected(header):
    assert not signature_is_valid(b'{"a": 1}', header, SECRET)


def test_signature_from_another_secret_rejected():
    raw = b'{"a": 1}'
    assert not signature_is_valid(raw, sign(raw, "other-secret"), SECRET)


def test_signature_covers_exact_bytes():
    # Same JSON, different whitespace: a different body, so a different signature.
    # This is why the route verifies the raw bytes before parsing.
    assert not signature_is_valid(b'{"a":1}', sign(b'{"a": 1}', SECRET), SECRET)


# ---------- status codes ----------

def test_valid_message_accepted(client, stored):
    response = post(client, SAMPLE)
    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "event_id": "evt_7f3a91c2", "message_id": "m-1"}
    assert stored[0].message.text == SAMPLE["message"]["text"]
    assert stored[0].customer.id == "cust_1042"


def test_duplicate_returns_200(client, monkeypatch):
    monkeypatch.setattr(ingest, "save_customer_message", lambda event: None)
    response = post(client, SAMPLE)
    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"


def test_missing_signature_401(client, stored):
    response = post(client, SAMPLE, signature=None)
    assert response.status_code == 401
    assert stored == []


def test_wrong_signature_401(client, stored):
    response = post(client, SAMPLE, signature=sign(b"something else", SECRET))
    assert response.status_code == 401
    assert stored == []


def test_tampered_body_401(client, stored):
    raw = json.dumps(SAMPLE).encode()
    signature = sign(raw, SECRET)
    tampered = raw.replace(b"Aisha", b"Mallory")
    assert post(client, tampered, signature=signature).status_code == 401


def test_invalid_json_400(client, stored):
    assert post(client, b'{"event_id": "evt_1", ').status_code == 400
    assert post(client, b"\xff\xfe not utf-8").status_code == 400
    assert post(client, b"").status_code == 400


def test_deeply_nested_json_400_not_500(client, stored):
    assert post(client, b"[" * 50_000).status_code == 400


def test_body_over_64kb_413(client, stored):
    payload = with_changes(message__text="x" * 70_000)
    assert post(client, payload).status_code == 413


@pytest.mark.parametrize("changes, field", [
    ({"event_id": DELETE}, "event_id"),
    ({"customer": DELETE}, "customer"),
    ({"customer__phone": ""}, "customer.phone"),
    ({"message__id": DELETE}, "message.id"),
    ({"timestamp": "yesterday"}, "timestamp"),
    ({"timestamp": "2026-11-03T10:15:22"}, "timestamp"),   # no timezone
    ({"message__text": "x" * 4001}, "message.text"),
    ({"message__text": "   "}, "message.text"),            # whitespace only
    ({"message__text": DELETE}, "message.text"),
    ({"message__text": "hi\u0000there"}, "message.text"),  # Postgres can't store NUL
    ({"customer__name": 42}, "customer.name"),
])
def test_schema_errors_422_name_the_field(client, stored, changes, field):
    response = post(client, with_changes(**changes))
    assert response.status_code == 422
    fields = [problem["field"] for problem in response.json()["detail"]]
    assert field in fields
    assert stored == []


def test_body_that_is_not_an_object_422(client, stored):
    assert post(client, [1, 2, 3]).status_code == 422


def test_422_does_not_echo_input(client, stored):
    secret_looking = "my card number is 4111 1111 1111 1111 " + "x" * 4000
    response = post(client, with_changes(message__text=secret_looking))
    assert response.status_code == 422
    assert "4111" not in response.text


def test_unknown_brand_422(client, monkeypatch):
    def raise_unknown(event):
        raise ingest.UnknownBrand(event.brand_id)

    monkeypatch.setattr(ingest, "save_customer_message", raise_unknown)
    response = post(client, with_changes(brand_id="someone-else"))
    assert response.status_code == 422
    assert response.json()["detail"][0]["field"] == "brand_id"


def test_unsupported_event_type_ignored(client, stored):
    # Only the envelope is required for events we don't handle.
    response = post(client, {"event_id": "evt_2", "type": "message.read", "brand_id": "verdant-co"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert stored == []


def test_image_message_ignored(client, stored):
    response = post(client, with_changes(message__type="image", message__text=DELETE))
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert stored == []


def test_extra_fields_are_ignored(client, stored):
    response = post(client, with_changes(message__language="en", source="whatsapp"))
    assert response.status_code == 200


def test_whitespace_trimmed(client, stored):
    post(client, with_changes(message__text="  Where is my order?  \n"))
    assert stored[0].message.text == "Where is my order?"


def test_storage_failure_returns_503_so_sender_retries(client, monkeypatch):
    def broken(event):
        raise RuntimeError("database is down")

    monkeypatch.setattr(ingest, "save_customer_message", broken)
    response = post(client, SAMPLE)
    assert response.status_code == 503
    assert "database is down" not in response.text  # internal errors aren't exposed


def test_get_not_allowed(client):
    assert client.get("/webhook").status_code == 405


def test_preview_is_one_line_and_capped():
    assert ingest._preview("Hello\n\n  there") == "Hello there"
    long = ingest._preview("word " * 100)
    assert len(long) <= ingest.PREVIEW_LENGTH and long.endswith("…")
