# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.metrics_store import OperatingMetricsStore
from hydra.runtime.operating_metrics import OperatingMetrics


def sample_metrics() -> OperatingMetrics:
    return OperatingMetrics(
        outbox_pending=1,
        outbox_dead_letters=0,
        oldest_pending_age_seconds=2.0,
        spans_total=4,
        spans_error=1,
        avg_span_duration_ms=12.5,
        spans_by_name={"routing": 2},
        deployments_by_state={"active": 1},
    )


def test_metrics_store_persists_snapshots(tmp_path):
    path = tmp_path / "hydra.db"
    store = OperatingMetricsStore(path)
    snapshot_id = store.append(sample_metrics())

    reopened = OperatingMetricsStore(path)
    rows = reopened.recent()

    assert rows[0]["id"] == snapshot_id
    assert rows[0]["metrics"]["spans_total"] == 4
    assert rows[0]["metrics"]["deployments_by_state"] == {"active": 1}


def test_metrics_store_bounds_history_limit(tmp_path):
    store = OperatingMetricsStore(tmp_path / "hydra.db")
    try:
        store.recent(0)
    except ValueError as exc:
        assert "between 1 and 1000" in str(exc)
    else:
        raise AssertionError("expected bounded metrics history")


def test_metrics_store_prunes_old_snapshots(tmp_path):
    store = OperatingMetricsStore(tmp_path / "hydra.db", max_snapshots=2)
    store.append(sample_metrics())
    store.append(sample_metrics())
    newest = store.append(sample_metrics())

    rows = store.recent(10)

    assert len(rows) == 2
    assert rows[0]["id"] == newest
