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

**Frontend** (Node 20+)

```
cd frontend
npm install
copy .env.example .env.local      [cp .env.example .env.local]
npm run dev                       opens http://localhost:5173
```
