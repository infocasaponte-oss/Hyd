# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""In-process sliding-window rate limiter shared by the API gateway and the runtime admin API.

A limit of zero or fewer requests disables limiting.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from fastapi import HTTPException, status


@dataclass(frozen=True)
class RateLimit:
    requests: int
    window_seconds: float = 60.0


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, requests: int | RateLimit, window_seconds: float = 60.0) -> None:
        if isinstance(requests, RateLimit):
            requests, window_seconds = requests.requests, requests.window_seconds
        if requests <= 0:
            return
        now = monotonic()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="HYDRA rate limit exceeded",
                )
            hits.append(now)
