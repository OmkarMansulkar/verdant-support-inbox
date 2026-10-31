"""Postgres connection pool, shared by request handlers and background tasks.

Usage:
    with db.connection() as conn:
        conn.execute(...)
The block is one transaction: it commits when the block ends normally and
rolls back if an exception escapes.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("app.db")

_pool: ConnectionPool | None = None


def open_pool(database_url: str) -> None:
    """Called once at startup. Doesn't wait for the database: if it's down,
    the app still starts and /health reports the problem."""
    global _pool
    _pool = ConnectionPool(
        database_url,
        min_size=1,
        max_size=5,  # well under the Supabase pooler's per-project limit
        # Test each connection before handing it out, so one the network
        # dropped overnight is replaced instead of failing the first request.
        check=ConnectionPool.check_connection,
        timeout=5,  # seconds to wait for a free connection before raising
        kwargs={
            "row_factory": dict_row,  # rows come back as dicts
            "prepare_threshold": None,  # no server-side prepared statements (breaks behind PgBouncer-style poolers)
            "connect_timeout": 5,
        },
        open=False,
    )
    _pool.open(wait=False)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[Connection]:
    if _pool is None:
        raise RuntimeError("Database pool is not open")
    with _pool.connection() as conn:
        yield conn


def is_healthy() -> bool:
    """Read a real table: proves the schema exists, and counts as database
    activity, which stops a free Supabase project from pausing."""
    try:
        with connection() as conn:
            conn.execute("select 1 from brands limit 1")
        return True
    except Exception:
        log.exception("health_check_db_failed")
        return False
