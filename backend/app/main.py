"""FastAPI app: wiring only. Each feature lives in its own module."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import get_settings
from app.log import setup_logging

# Local development reads backend/.env. On Render there is no .env file, and
# load_dotenv never overrides variables that are already set.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

setup_logging()
log = logging.getLogger("app")
settings = get_settings()  # raises at startup if any variable is missing


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool(settings.database_url)
    log.info("app_started", extra={"cors_origins": settings.cors_origins})
    yield
    db.close_pool()
    log.info("app_stopped")


app = FastAPI(title="Verdant & Co Support Inbox API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/")
def root() -> dict:
    return {"service": "verdant-support-inbox-api", "docs": "/docs"}


# GET and HEAD: uptime monitors often send HEAD, and a GET-only route answers 405.
@app.api_route("/health", methods=["GET", "HEAD"])
# Answers 503 when the database is unreachable, so the uptime monitor emails us
# about database problems too, not only when the server itself is down.
def health(response: Response) -> dict:
    if not db.is_healthy():
        response.status_code = 503
        return {"status": "error", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
