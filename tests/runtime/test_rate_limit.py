# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest
from fastapi import HTTPException

from hydra.runtime.rate_limit import RateLimit, SlidingWindowRateLimiter


def test_rate_limiter_rejects_after_limit():
    limiter = SlidingWindowRateLimiter()
    limit = RateLimit(requests=2, window_seconds=60)
    limiter.check("client", limit)
    limiter.check("client", limit)
    with pytest.raises(HTTPException) as exc:
        limiter.check("client", limit)
    assert exc.value.status_code == 429
