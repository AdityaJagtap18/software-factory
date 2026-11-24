"""Minimal in-memory sliding-window rate limiter for sensitive auth routes
(P0-3 of the security hygiene audit). Single-process only -- a multi-worker
or multi-instance deployment needs a shared store (e.g. Redis) instead, but
this backend runs as a single uvicorn process today, so that gap is noted
here rather than built ahead of need."""

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

_lock = Lock()
_hits: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce(request: Request, scope: str, max_requests: int, window_seconds: float = 60.0) -> None:
    """Raises 429 if `scope` has already seen `max_requests` hits from this
    client within the trailing `window_seconds`; otherwise records this hit."""
    key = f"{scope}:{_client_ip(request)}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        hits = _hits[key]
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= max_requests:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests. Please wait before trying again.",
            )
        hits.append(now)


def reset() -> None:
    """Test-only: clears all tracked hits between test cases."""
    with _lock:
        _hits.clear()
