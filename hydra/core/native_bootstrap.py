# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.core.outbox_worker import OutboxWorker
from hydra.core.outbox_recovery import RecoveryResult, recover_pending


@dataclass(frozen=True)
class BootstrapResult:
    recovery: RecoveryResult


def bootstrap_runtime(worker: OutboxWorker) -> BootstrapResult:
    return BootstrapResult(recovery=recover_pending(worker))
