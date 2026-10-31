# Verdant & Co — AI Support Inbox

Work in progress. The final one-page README (decisions, cuts, AI notes, answers) comes at the end.

## Run locally (Windows commands; macOS/Linux in brackets)

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
