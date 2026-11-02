# Verdant & Co — AI Support Inbox

Work in progress. The final one-page README (decisions, cuts, AI notes, answers) comes at the end.

## Run locally (Windows commands; macOS/Linux in brackets)

**Database** (a free Supabase project, once)

1. SQL editor: run `backend/schema.sql`.
2. Authentication > Sign In / Providers: turn off "Allow new users to sign up". Authentication > Users > Add user: create the agents (tick "Auto confirm user").
3. SQL editor: run `backend/seed.sql` (edit its agent emails first if yours differ). The final query should list one row per agent.
4. To wipe conversations later: run `backend/reset.sql`, then `backend/seed.sql` again.

**Backend** (Python 3.13)

```
cd backend
py -3.13 -m venv .venv            [python3.13 -m venv .venv]
.venv\Scripts\activate            [source .venv/bin/activate]
pip install -r requirements-dev.txt
copy .env.example .env            [cp .env.example .env]   then fill in the values
uvicorn app.main:app --reload --port 8000
pytest
```

**Test the webhook** (from the repo root, with the backend running; any Python 3.10+, no packages needed; the secret is read from `backend/.env` or the `WEBHOOK_SECRET` variable)

```
python scripts/send_webhook.py "What is your return policy?"
python scripts/run_test_cases.py                 the 5 sample messages + failure cases
python scripts/run_test_cases.py --url https://verdant-support-inbox-api.onrender.com/webhook
```

**Try the AI drafts** (calls the real LLM with the server's prompt; no database needed): `backend\.venv\Scripts\python scripts\try_drafts.py` [`backend/.venv/bin/python scripts/try_drafts.py`]

**Frontend** (Node 20+)

```
cd frontend
npm install
copy .env.example .env.local      [cp .env.example .env.local]
npm run dev                       opens http://localhost:5173
```
