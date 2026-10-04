# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility re-export; the implementation lives in :mod:`hydra.governance.rate_limit`."""
from hydra.governance.rate_limit import RateLimit, SlidingWindowRateLimiter

__all__ = ["RateLimit", "SlidingWindowRateLimiter"]
