"""In-memory sliding-window rate limiter and proxy-safe client IP helper."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def extract_client_ip(request: Request) -> str:
    """Extract client IP, trusting CF-Connecting-IP strictly from local cloudflared loopback."""
    peer = request.client.host if request.client else "127.0.0.1"
    if peer in _LOOPBACK_HOSTS:
        cf_ip = request.headers.get("cf-connecting-ip", "").strip()
        if cf_ip:
            return cf_ip
        xff = request.headers.get("x-forwarded-for", "").strip()
        if xff:
            return xff.split(",")[0].strip()
    return peer


class SlidingWindowLimiter:
    """Thread-safe per-key sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_sec: int) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def check_or_raise(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window_sec
        with self._lock:
            dq = self._buckets[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self.max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Занадто багато запитів. Зачекайте хвилину.",
                )
            dq.append(now)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


auth_ip_limiter = SlidingWindowLimiter(max_requests=10, window_sec=60)
explain_ip_limiter = SlidingWindowLimiter(max_requests=15, window_sec=60)
report_ip_limiter = SlidingWindowLimiter(max_requests=8, window_sec=60)
