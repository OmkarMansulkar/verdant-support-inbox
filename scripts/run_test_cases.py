"""Run the brief's five sample messages and the failure cases against a webhook.

  python scripts/run_test_cases.py                                   # local server
  python scripts/run_test_cases.py --url https://verdant-support-inbox-api.onrender.com/webhook

Each run uses fresh ids, so it can be repeated. Prints PASS/FAIL per case and
exits non-zero if anything failed. Uses only the standard library.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from send_webhook import DEFAULT_URL, load_secret, make_event, send, sign

# The brief's sample messages, spread over the seeded test customers.
SAMPLES = [
    ("cust_1042", "Aisha Khan", "+919800000001",
     "Hi, my order #4471 hasn't arrived yet. Can I change the delivery address?"),
    ("cust_1043", "Rohan Mehta", "+919800000002", "What is your return policy?"),
    ("cust_1044", "Meera Iyer", "+919800000003", "Do you deliver to Dubai?"),
    ("cust_1043", "Rohan Mehta", "+919800000002", "Is cash on delivery available for a ₹3,500 order?"),
    ("cust_1044", "Meera Iyer", "+919800000003", "I think I'm allergic to the serum I bought. What should I do?"),
]


class Runner:
    def __init__(self, url: str, secret: str):
        self.url = url
        self.secret = secret
        self.results: list[bool] = []

    def post(self, body: dict | bytes, signature: str | None = "good", signed_body: bytes | None = None):
        """Send a dict (as JSON) or raw bytes. signature: 'good', None, or a literal header value.
        signed_body: sign these bytes instead of the ones sent (tampering test)."""
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        if signature == "good":
            signature = sign(signed_body or raw, self.secret)
        status, response_body, _ = send(self.url, raw, signature)
        return status, response_body

    def check(self, label: str, result: tuple, expected_status: int, expected_body_status: str | None = None):
        status, body = result
        ok = status == expected_status
        if expected_body_status is not None:
            ok = ok and isinstance(body, dict) and body.get("status") == expected_body_status
        self.results.append(ok)
        shown = (body.get("status") or body.get("detail")) if isinstance(body, dict) else body
        print(f"{'PASS' if ok else 'FAIL'}  {label:<55} HTTP {status}  {json.dumps(shown)[:80]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    run = Runner(parser.parse_args().url, load_secret())
    print(f"Target: {run.url}")

    print("\n-- Sample messages (expect 200 accepted, well under 1000 ms)")
    for customer_id, name, phone, text in SAMPLES:
        raw = json.dumps(make_event(text, customer_id, name, phone)).encode()
        status, body, ms = send(run.url, raw, sign(raw, run.secret))
        run.check(f"{text[:40]}… ({ms} ms)", (status, body), 200, "accepted")

    print("\n-- Duplicates and retries (expect 200 duplicate, nothing stored twice)")
    event = make_event("Retry test: where is my order?")
    run.post(event)
    run.check("same event delivered again", run.post(event), 200, "duplicate")
    resent = make_event("Retry test: where is my order?", message_id=event["message"]["id"])
    run.check("same message.id under a new event_id", run.post(resent), 200, "duplicate")

    burst = make_event("Concurrency test: five copies at once")
    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(lambda _: run.post(burst), range(5)))
    statuses = sorted(body.get("status") for _, body in outcomes)
    ok = statuses == ["accepted", "duplicate", "duplicate", "duplicate", "duplicate"]
    run.results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {'5 identical deliveries in parallel -> 1 stored':<55} {statuses}")

    print("\n-- Signatures (expect 401)")
    run.check("missing X-Signature", run.post(make_event("hi"), signature=None), 401)
    run.check("wrong signature", run.post(make_event("hi"), signature="sha256=" + "0" * 64), 401)
    other = json.dumps(make_event("hi")).encode()
    run.check("signed with another secret", run.post(other, signature=sign(other, "wrong-secret")), 401)
    original = json.dumps(make_event("original text")).encode()
    tampered = original.replace(b"original text", b"tampered text")
    run.check("body changed after signing", run.post(tampered, signed_body=original), 401)

    print("\n-- Malformed payloads (expect 4xx, never 5xx)")
    run.check("not valid JSON", run.post(b'{"event_id": "evt_broken", '), 400)
    no_customer = make_event("hi")
    del no_customer["customer"]
    run.check("missing customer", run.post(no_customer), 422)
    no_timezone = make_event("hi")
    no_timezone["timestamp"] = "2026-11-03T10:15:22"
    run.check("timestamp without timezone", run.post(no_timezone), 422)
    run.check("empty message text", run.post(make_event("   ")), 422)
    run.check("text over 4000 characters", run.post(make_event("x" * 4001)), 422)
    run.check("unknown brand_id", run.post(make_event("hi", brand_id="other-brand")), 422)
    run.check("body over 64 KB", run.post(make_event("x" * 70_000)), 413)

    print("\n-- Events we deliberately skip (expect 200 ignored)")
    read_receipt = {"event_id": make_event("x")["event_id"], "type": "message.read", "brand_id": "verdant-co"}
    run.check("event type message.read", run.post(read_receipt), 200, "ignored")
    image = make_event("x")
    image["message"] = {"id": image["message"]["id"], "type": "image"}
    run.check("image message", run.post(image), 200, "ignored")

    passed = sum(run.results)
    print(f"\n{passed}/{len(run.results)} passed")
    sys.exit(0 if passed == len(run.results) else 1)


if __name__ == "__main__":
    main()
