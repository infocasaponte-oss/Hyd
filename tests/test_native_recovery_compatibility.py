# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from unittest.mock import Mock

from hydra.core import native_bootstrap, outbox_recovery
from hydra.core.outbox_worker import WorkerResult
from hydra.runtime import api, bootstrap, startup_recovery


def test_legacy_recovery_and_http_bootstrap_share_implementation():
    assert bootstrap is native_bootstrap
    assert startup_recovery is outbox_recovery
    assert api.bootstrap_runtime is native_bootstrap.bootstrap_runtime


def test_recovery_stops_when_only_retries_remain():
    worker = Mock()
    worker.run_once.side_effect = [
        WorkerResult(published=2, retried=1, dead_lettered=1),
        WorkerResult(published=0, retried=3, dead_lettered=2),
    ]
    result = outbox_recovery.recover_pending(worker, batch_size=7)
    assert result == outbox_recovery.RecoveryResult(2, 2, 4, 3)
    assert worker.run_once.call_count == 2
    worker.run_once.assert_called_with(7)


def test_recovery_respects_max_batches():
    worker = Mock()
    worker.run_once.return_value = WorkerResult(published=1, retried=0, dead_lettered=0)
    result = outbox_recovery.recover_pending(worker, max_batches=3)
    assert result.batches == 3
    assert result.published == 3
    assert worker.run_once.call_count == 3
