"""Sign in as an agent with the real Supabase Auth and call the agent API.

Proves the whole sign-in chain works (Supabase password sign-in -> token ->
our API verifies it with Supabase -> agents table) before relying on the UI.
Uses only the standard library; reads SUPABASE_URL and SUPABASE_ANON_KEY from
backend/.env (or the environment). Asks for the password (or reads
AGENT_PASSWORD, for scripted runs); never stores it.

  python scripts/check_agent_api.py priya@example.com
  python scripts/check_agent_api.py priya@example.com --api https://verdant-support-inbox-api-sg.onrender.com
"""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / "backend" / ".env"


def setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not value:
        sys.exit(f"Missing {name}: set it or add it to backend/.env")
    return value


def request(method: str, url: str, headers: dict, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except urllib.error.URLError as error:  # DNS failure, refused connection, timeout
        host = urllib.parse.urlsplit(url).netloc
        sys.exit(f"Could not reach {host}: {error.reason}\n"
                 "Check the URL: SUPABASE_URL in backend/.env, or --api (is the server running?).")
    try:
        return status, json.loads(raw or b"null")
    except ValueError:  # e.g. an HTML error page from a proxy during a deploy
        return status, raw.decode(errors="replace")[:200]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows: customer text may contain ₹
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    supabase_url, anon_key = setting("SUPABASE_URL").rstrip("/"), setting("SUPABASE_ANON_KEY")

    password = os.environ.get("AGENT_PASSWORD") or getpass.getpass(f"Password for {args.email}: ")
    status, session = request("POST", f"{supabase_url}/auth/v1/token?grant_type=password",
                              {"apikey": anon_key}, {"email": args.email, "password": password})
    if status != 200:
        sys.exit(f"Supabase sign-in failed (HTTP {status}): {session}")
    auth = {"Authorization": f"Bearer {session['access_token']}"}
    print("1. Signed in with Supabase")

    status, me = request("GET", f"{args.api}/api/agent/me", auth)
    print(f"2. GET /api/agent/me -> HTTP {status}: {me}")
    if status != 200:
        sys.exit("   The API didn't accept the token (see the status code above).")

    status, inbox = request("GET", f"{args.api}/api/agent/conversations", auth)
    print(f"3. GET /api/agent/conversations -> HTTP {status}, {len(inbox)} conversation(s)")
    for c in inbox[:5]:
        flag = " [needs attention]" if c["needs_human"] else ""
        print(f"   {c['customer_name']:<14} draft={c['draft_status'] or '-':<8}{flag}  {c['last_message_preview'][:50]}")

    if inbox:
        status, convo = request("GET", f"{args.api}/api/agent/conversations/{inbox[0]['id']}", auth)
        draft = convo["draft"]
        print(f"4. Newest conversation: {len(convo['messages'])} message(s); "
              f"draft: {draft['status'] + ' - ' + (draft['body'] or draft['error'] or '')[:70] if draft else 'none'}")
    status, _ = request("GET", f"{args.api}/api/agent/me", {"Authorization": "Bearer not-a-real-token"})
    print(f"5. Same call with a fake token -> HTTP {status} (expect 401)")


if __name__ == "__main__":
    main()
