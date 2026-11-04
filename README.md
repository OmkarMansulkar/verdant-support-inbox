# Verdant & Co — AI Support Inbox

An LLM drafts support replies from the knowledge base; an agent edits and approves them. Nothing is sent automatically.

**App** https://verdant-support-inbox.vercel.app · **Webhook** https://verdant-support-inbox-api-sg.onrender.com/webhook

**Agent sign-in:** two test accounts (Priya, Rahul); credentials are in the submission form.

### Run locally

1. **Supabase:** run `backend/schema.sql`, turn off sign-ups, add agent users, run `backend/seed.sql` (edit its emails).
2. **Backend** (Python 3.13, in `backend`): `python -m venv .venv`, activate it (`.venv\Scripts\activate` or `source .venv/bin/activate`) → `pip install -r requirements-dev.txt` → fill in a copy of `.env.example` as `.env` → `uvicorn app.main:app --port 8000`; tests: `pytest`.
3. **Frontend** (Node 20+, in `frontend`): `npm install` → fill in `.env.example` as `.env.local` → `npm run dev`.
4. **Webhook tests** (repo root): `python scripts/run_test_cases.py [--url <webhook>]`: 5 samples + 20 failure cases.

**Code map:** `backend/app` has one module per step (`webhook` → `ingest` → `drafts` → `llm`); the UI is in `frontend/src`.

### Decisions

**Stack:** React + Vite on Vercel; FastAPI on Render (Python: the language I can defend line by line); Supabase Postgres + Auth; plain SQL, so transactions stay visible; Groq `gpt-oss-120b` (fallback `gpt-oss-20b`).

- **Webhook:** size cap (413) → HMAC of raw bytes, constant-time (401) → JSON (400) → schema (422) → save → 200 in ~0.3 s; the LLM runs afterwards. DB down → 503, so the sender retries.
- **The database enforces correctness:** unique `event_id`/`message.id` turn retries into a no-op 200 `duplicate`; a partial unique index keeps one open conversation per customer; approval is a conditional update plus a unique `source_draft_id`, so two agents approving at once get one reply and a 409.
- **One code path:** the Customer view signs a webhook event on the server and calls the same `handle_webhook()`. Customer endpoints only read `messages`, so drafts can't leak. A new message supersedes the pending draft.
- **AI:** the whole KB (~250 tokens) is in the system prompt; the conversation is passed as JSON data, not instructions. Structured output adds a needs-human flag and reason. Missing from the KB means "unknown", not "no" (Dubai → "I'll check with the team"); health concerns → stop using, see a doctor, flagged; a pattern check flags obvious injection. Large KBs would need per-brand embeddings (pgvector).
- **Operations:** JSON logs trace `event_id` → `message_id` → `draft_id` (no message text); UptimeRobot watches `/health`; `brand_id` is on every row.

**Cut for time:** real-time updates (it polls), a retry queue, debouncing, replay protection, Sentry, LLM evals.

### AI help, and one mistake

I paired with Claude on planning, reviews, tests and prompts. It picked Groq's Llama 3.x models from memory, but Groq had retired them in August 2026, so every draft would have failed. Tests with a fake provider passed; my first real-model run caught it. I switched models, and failed drafts now show the provider's error.

### Two questions

**2 a.m. failure.** The message is saved before the AI runs, so the agent sees it marked "Draft failed" with the reason and a Retry button, and can still write a reply; if the database was down, the platform got a 503 and retried, and UptimeRobot emailed us. I'd search Render's logs for the `event_id` and follow its `message_id` and `draft_id` to the failing step.

**20 brands.** First, a webhook secret per brand: today one shared secret signs every request and the brand comes from the body, so one brand's sender could write into another's inbox. Then knowledge bases move from repo files into a per-brand table that brand admins edit, and the free LLM tier (8K tokens/minute) becomes a paid tier behind a queue.
