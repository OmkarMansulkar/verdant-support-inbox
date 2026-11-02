"""Per-IP rate limiting for the public (no sign-in) Customer-view endpoints.

Each customer message triggers an LLM call, so without a limit anyone could
spend the whole free-tier LLM budget in a minute.

In memory, one process: counters reset on restart, and with several workers
each would count separately. Fine for one uvicorn worker (D29); at scale the
counters would move to Redis or the database.
"""

import logging
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

log = logging.getLogger("app.rate_limit")

MAX_TRACKED_CLIENTS = 10_000  # above this, forget clients that have gone quiet


class RateLimiter:
    """Sliding window: at most `max_requests` per `window_seconds` per key."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        # Sync endpoints run in a thread pool, so two requests can update the
        # counters at the same moment.
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            if len(self._hits) > MAX_TRACKED_CLIENTS:
                self._forget_quiet_clients(cutoff)
            return True

    def _forget_quiet_clients(self, cutoff: float) -> None:
        quiet = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in quiet:
            del self._hits[key]


def client_ip(request: Request) -> str:
    """The visitor's IP address.

    On Render every request passes through Cloudflare, which sets
    True-Client-IP to the address it saw and overwrites any value the client
    sent. X-Forwarded-For is not usable there: Render appends to whatever the
    client sent (so the left-most entry can be forged) and the right-most entry
    is Cloudflare's own address (shared by everyone). Locally there is no
    proxy, so the socket address is the client.
    """
    forwarded = request.headers.get("true-client-ip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def limit(limiter: RateLimiter, name: str):
    """A FastAPI dependency that answers 429 once a client exceeds `limiter`."""

    def check(request: Request) -> None:
        if not limiter.allow(client_ip(request)):
            # Not the address itself (personal data); which header it came from
            # is enough to confirm the proxy setup works in production.
            source = "true-client-ip" if request.headers.get("true-client-ip") else "socket"
            log.warning("rate_limited", extra={"limit": name, "ip_source": source, "path": request.url.path})
            raise HTTPException(
                429,
                "Too many requests; please wait a minute and try again",
                headers={"Retry-After": str(int(limiter.window_seconds))},
            )

    check.__name__ = f"rate_limit_{name}"
    return check
