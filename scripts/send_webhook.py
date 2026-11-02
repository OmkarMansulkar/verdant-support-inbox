"""Send one signed test message to the webhook, the way the chat platform would.

Uses only the Python standard library, so any Python 3.10+ works.

Examples (from the repo root):
  python scripts/send_webhook.py "What is your return policy?"
  python scripts/send_webhook.py "Do you deliver to Dubai?" --customer cust_1043 --name "Rohan Mehta" --phone +919800000002
  python scripts/send_webhook.py "hello" --url https://verdant-support-inbox-api.onrender.com/webhook
  python scripts/send_webhook.py "hello" --signature bad      # expect 401

The secret comes from the WEBHOOK_SECRET environment variable, or else from
backend/.env. It is never stored in this script.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL = "http://localhost:8000/webhook"
ENV_FILE = Path(__file__).resolve().parent.parent / "backend" / ".env"


def load_secret() -> str:
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not secret and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("WEBHOOK_SECRET="):
                secret = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not secret:
        sys.exit("No secret: set WEBHOOK_SECRET or add it to backend/.env")
    return secret


def sign(raw_body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def make_event(text: str, customer_id="cust_1042", name="Aisha Khan", phone="+919800000001",
               event_id=None, message_id=None, brand_id="verdant-co") -> dict:
    suffix = uuid.uuid4().hex[:8]  # fresh ids each run, so reruns aren't duplicates
    return {
        "event_id": event_id or f"evt_test_{suffix}",
        "type": "message.received",
        "brand_id": brand_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "customer": {"id": customer_id, "name": name, "phone": phone},
        "message": {"id": message_id or f"msg_test_{suffix}", "type": "text", "text": text},
    }


def send(url: str, raw_body: bytes, signature: str | None, timeout: float = 60) -> tuple[int, dict | str, int]:
    """POST raw bytes; returns (status code, parsed body, milliseconds)."""
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Signature"] = signature
    request = urllib.request.Request(url, data=raw_body, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, text = response.status, response.read().decode()
    except urllib.error.HTTPError as error:  # 4xx/5xx still carry a body
        status, text = error.code, error.read().decode()
    elapsed_ms = round((time.monotonic() - started) * 1000)
    try:
        return status, json.loads(text), elapsed_ms
    except ValueError:
        return status, text, elapsed_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Send one signed webhook message.")
    parser.add_argument("text", help="message text")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--customer", default="cust_1042", help="customer id")
    parser.add_argument("--name", default="Aisha Khan")
    parser.add_argument("--phone", default="+919800000001")
    parser.add_argument("--event-id", help="reuse to test duplicate delivery")
    parser.add_argument("--message-id", help="reuse to test a re-sent message")
    parser.add_argument("--signature", choices=["good", "bad", "none"], default="good")
    args = parser.parse_args()

    event = make_event(args.text, args.customer, args.name, args.phone, args.event_id, args.message_id)
    raw = json.dumps(event).encode()
    signature = {"good": sign(raw, load_secret()), "bad": "sha256=" + "0" * 64, "none": None}[args.signature]

    status, body, elapsed_ms = send(args.url, raw, signature)
    print(f"event_id={event['event_id']}  message.id={event['message']['id']}")
    print(f"HTTP {status} in {elapsed_ms} ms")
    print(json.dumps(body, indent=2) if isinstance(body, dict) else body)


if __name__ == "__main__":
    main()
