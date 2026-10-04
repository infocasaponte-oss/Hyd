# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility alias for the shared outbox worker."""
import sys
from hydra.core import outbox_worker as _implementation
from hydra.core.outbox_worker import RetryPolicy, WorkerResult, OutboxWorker

__all__ = ["RetryPolicy", "WorkerResult", "OutboxWorker"]
sys.modules[__name__] = _implementation
