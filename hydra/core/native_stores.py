# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""PostgreSQL versions of the runtime-line stores kept in ``hydra.db`` (HYDRA_RUNTIME_BACKEND).

Same interfaces as the SQLite stores, shared by every node:

* ``PostgresCaptureUnitOfWork``: ``task_commits`` and the transactional outbox (``runtime_outbox``,
  whose workers claim messages, see ``hydra.core.capture_outbox_pg``) in one transaction;
* ``PostgresDeploymentEvidenceStore``: evidence accepted at each promotion (``deployment_evidence``);
* ``PostgresOperatingMetricsStore``: operating metrics snapshots (``operating_metrics``, with the node);
* ``PostgresRuntimeHealthStore``: circuit breakers per node and variant (``runtime_health``). A node
  restores its own breakers: the health of a runtime as seen from one node says nothing about another;
* ``PostgresTraceStore``: cognitive spans of every node (``runtime_spans``, bounded), so the operating
  metrics describe the cluster rather than the node that answered the admin request.

``open_runtime_stores`` picks SQLite or PostgreSQL and, on PostgreSQL, imports an existing
``hydra.db`` once (unpublished outbox messages and task commits by id; evidence, metrics and this
node's breakers when the tables are still empty). Requires ``psycopg`` 3."""

from __future__ import annotations

import json
import logging
import socket
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID

from hydra.core.capture_outbox_pg import PostgresOutbox
from hydra.core.task_commit import CaptureUnitOfWork, TaskCommit
from hydra.registry.circuit_breaker import Breaker as CircuitBreaker
from hydra.registry.circuit_breaker import CircuitState
from hydra.deploy.deployment_evidence import CanaryEvidence, ShadowEvidence
from hydra.deploy.deployment_evidence_store import DeploymentEvidenceStore
from hydra.observability.operating_store import OperatingMetricsStore
from hydra.observability.spans import TraceStore
from hydra.observability.operating import OperatingMetrics
from hydra.deploy.runtime_health_store import RuntimeHealthStore

log = logging.getLogger("hydra.runtime")

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_commits (
    task_id      UUID PRIMARY KEY,
    trace_id     TEXT NOT NULL,
    status       TEXT NOT NULL,
    result       JSONB NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS deployment_evidence (
    id         BIGSERIAL PRIMARY KEY,
    variant_id TEXT NOT NULL,
    phase      TEXT NOT NULL,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS deployment_evidence_variant_phase ON deployment_evidence (variant_id, phase, id);
CREATE TABLE IF NOT EXISTS operating_metrics (
    id          BIGSERIAL PRIMARY KEY,
    node        TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    payload     JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_spans (
    id          BIGSERIAL PRIMARY KEY,
    node        TEXT NOT NULL,
    span        JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS runtime_health (
    node              TEXT NOT NULL,
    variant_id        TEXT NOT NULL,
    state             TEXT NOT NULL,
    failures          INTEGER NOT NULL,
    failure_threshold INTEGER NOT NULL,
    recovery_seconds  DOUBLE PRECISION NOT NULL,
    opened_at_wall    DOUBLE PRECISION,
    updated_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (node, variant_id)
);
"""


class _Connections:
    """One autocommit connection per thread; the schema is created on first use."""

    def __init__(self, url: str) -> None:
        import psycopg  # optional dependency
        from psycopg.types.json import Jsonb

        self._psycopg, self.jsonb = psycopg, Jsonb
        self.url = url
        self._local = threading.local()
        con = self.get()
        with con.transaction():
            con.execute(SCHEMA)

    def get(self):
        con = getattr(self._local, "con", None)
        if con is None or con.closed:
            con = self._psycopg.connect(self.url, autocommit=True)
            self._local.con = con
        return con


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


class PostgresCaptureUnitOfWork:
    def __init__(self, db: _Connections, outbox: PostgresOutbox) -> None:
        self.db = db
        self.outbox = outbox

    def commit_terminal(self, commit: TaskCommit, *, event_payload: dict[str, Any],
                        provenance_payload: dict[str, Any], corpus_payload: dict[str, Any] | None = None) -> None:
        with self.outbox.transaction() as connection:
            connection.execute(
                "INSERT INTO task_commits (task_id, trace_id, status, result, committed_at) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (task_id) DO UPDATE SET trace_id = excluded.trace_id, "
                "status = excluded.status, result = excluded.result, committed_at = excluded.committed_at",
                (commit.task_id, commit.trace_id, commit.status, self.db.jsonb(commit.result), datetime.now(UTC)))
            for topic, payload in (("event", event_payload), ("provenance", provenance_payload),
                                   ("corpus", corpus_payload)):
                if payload is not None:
                    self.outbox.enqueue(connection, topic=topic, aggregate_id=commit.task_id,
                                        trace_id=commit.trace_id, payload=payload)

    def get_task_commit(self, task_id: UUID) -> TaskCommit | None:
        row = self.db.get().execute("SELECT task_id, trace_id, status, result FROM task_commits WHERE task_id = %s",
                                    (task_id,)).fetchone()
        if row is None:
            return None
        return TaskCommit(task_id=UUID(str(row[0])), trace_id=row[1], status=row[2], result=row[3])


class PostgresDeploymentEvidenceStore:
    def __init__(self, db: _Connections) -> None:
        self.db = db

    def append_shadow(self, variant_id: str, evidence: ShadowEvidence) -> None:
        self._append(variant_id, "shadow", asdict(evidence))

    def append_canary(self, variant_id: str, evidence: CanaryEvidence) -> None:
        self._append(variant_id, "canary", asdict(evidence))

    def _append(self, variant_id: str, phase: str, payload: dict) -> None:
        self.db.get().execute("INSERT INTO deployment_evidence (variant_id, phase, payload, created_at) "
                              "VALUES (%s, %s, %s, %s)", (variant_id, phase, self.db.jsonb(payload), datetime.now(UTC)))

    def latest_shadow(self, variant_id: str) -> ShadowEvidence | None:
        payload = self._latest(variant_id, "shadow")
        return ShadowEvidence(**payload) if payload is not None else None

    def latest_canary(self, variant_id: str) -> CanaryEvidence | None:
        payload = self._latest(variant_id, "canary")
        return CanaryEvidence(**payload) if payload is not None else None

    def _latest(self, variant_id: str, phase: str) -> dict | None:
        row = self.db.get().execute("SELECT payload FROM deployment_evidence WHERE variant_id = %s AND phase = %s "
                                    "ORDER BY id DESC LIMIT 1", (variant_id, phase)).fetchone()
        return row[0] if row is not None else None


class PostgresOperatingMetricsStore:
    def __init__(self, db: _Connections, *, max_snapshots: int = 10_000, node: str | None = None) -> None:
        if max_snapshots < 1:
            raise ValueError("max_snapshots must be positive")
        self.db = db
        self.max_snapshots = max_snapshots
        self.node = node or socket.gethostname()

    def append(self, metrics: OperatingMetrics) -> int:
        con = self.db.get()
        with con.transaction():
            snapshot_id = con.execute(
                "INSERT INTO operating_metrics (node, captured_at, payload) VALUES (%s, %s, %s) RETURNING id",
                (self.node, datetime.now(UTC), self.db.jsonb(asdict(metrics)))).fetchone()[0]
            con.execute("DELETE FROM operating_metrics WHERE id <= "
                        "(SELECT id FROM operating_metrics ORDER BY id DESC OFFSET %s LIMIT 1)", (self.max_snapshots,))
        return int(snapshot_id)

    def recent(self, limit: int = 100) -> list[dict]:
        if limit < 1 or limit > 1000:
            raise ValueError("Metrics history limit must be between 1 and 1000")
        rows = self.db.get().execute("SELECT id, captured_at, payload FROM operating_metrics ORDER BY id DESC LIMIT %s",
                                     (limit,)).fetchall()
        return [{"id": int(i), "captured_at": _iso(at), "metrics": payload} for i, at, payload in rows]


class PostgresRuntimeHealthStore:
    def __init__(self, db: _Connections, node: str | None = None) -> None:
        self.db = db
        self.node = node or socket.gethostname()

    def save(self, variant_id: str, breaker: CircuitBreaker) -> None:
        opened_at_wall = None
        if breaker.opened_at is not None:
            opened_at_wall = datetime.now(UTC).timestamp() - max(monotonic() - breaker.opened_at, 0.0)
        self.db.get().execute(
            "INSERT INTO runtime_health (node, variant_id, state, failures, failure_threshold, recovery_seconds, "
            "opened_at_wall, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (node, variant_id) DO UPDATE SET state = excluded.state, failures = excluded.failures, "
            "failure_threshold = excluded.failure_threshold, recovery_seconds = excluded.recovery_seconds, "
            "opened_at_wall = excluded.opened_at_wall, updated_at = excluded.updated_at",
            (self.node, variant_id, breaker.state.value, breaker.failures, breaker.failure_threshold,
             breaker.recovery_seconds, opened_at_wall, datetime.now(UTC)))

    def load(self) -> dict[str, CircuitBreaker]:
        rows = self.db.get().execute(
            "SELECT variant_id, state, failures, failure_threshold, recovery_seconds, opened_at_wall "
            "FROM runtime_health WHERE node = %s", (self.node,)).fetchall()
        now_wall, now_mono = datetime.now(UTC).timestamp(), monotonic()
        restored: dict[str, CircuitBreaker] = {}
        for variant_id, state, failures, threshold, recovery, opened_at_wall in rows:
            breaker = CircuitBreaker(failure_threshold=threshold, recovery_seconds=recovery,
                                     state=CircuitState(state), failures=failures)
            if opened_at_wall is not None:
                breaker.opened_at = now_mono - max(now_wall - float(opened_at_wall), 0.0)
            restored[variant_id] = breaker
        return restored


class PostgresTraceStore:
    """Same interface as ``hydra.observability.spans.TraceStore``; keeps the last ``max_spans``."""

    def __init__(self, db: _Connections, *, max_spans: int = 50_000, node: str | None = None) -> None:
        self.db = db
        self.max_spans = max_spans
        self.node = node or socket.gethostname()
        self._appended = 0

    def append(self, span) -> None:
        body = json.loads(json.dumps(asdict(span), sort_keys=True, default=str))
        con = self.db.get()
        con.execute("INSERT INTO runtime_spans (node, span) VALUES (%s, %s)", (self.node, self.db.jsonb(body)))
        self._appended += 1
        if self._appended % 1000 == 0:  # bounded history, trimmed now and then rather than per span
            con.execute("DELETE FROM runtime_spans WHERE id <= "
                        "(SELECT id FROM runtime_spans ORDER BY id DESC OFFSET %s LIMIT 1)", (self.max_spans,))

    def recent(self, limit: int = 10_000) -> list[dict]:
        rows = self.db.get().execute("SELECT span FROM runtime_spans ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
        return [span for (span,) in reversed(rows)]


# ------------------------------------------------------------------------------------------ selection
@dataclass
class RuntimeStores:
    capture_uow: CaptureUnitOfWork | PostgresCaptureUnitOfWork
    deployment_evidence: DeploymentEvidenceStore | PostgresDeploymentEvidenceStore
    operating_metrics: OperatingMetricsStore | PostgresOperatingMetricsStore
    runtime_health: RuntimeHealthStore | PostgresRuntimeHealthStore
    backend: str = "sqlite"
    traces: TraceStore | PostgresTraceStore | None = None


def open_runtime_stores(runtime_db: str | Path, postgres_url: str = "") -> RuntimeStores:
    """SQLite ``runtime_db`` without ``postgres_url``; otherwise PostgreSQL, importing ``runtime_db``
    once if it exists (it is kept as is)."""
    if not postgres_url:
        return RuntimeStores(CaptureUnitOfWork(runtime_db), DeploymentEvidenceStore(runtime_db),
                             OperatingMetricsStore(runtime_db), RuntimeHealthStore(runtime_db), traces=TraceStore())
    db = _Connections(postgres_url)
    outbox = PostgresOutbox(postgres_url, table="runtime_outbox")
    stores = RuntimeStores(PostgresCaptureUnitOfWork(db, outbox), PostgresDeploymentEvidenceStore(db),
                           PostgresOperatingMetricsStore(db), PostgresRuntimeHealthStore(db), backend="postgres",
                           traces=PostgresTraceStore(db))
    if Path(runtime_db).is_file():
        imported = import_sqlite(Path(runtime_db), db, outbox, stores.runtime_health.node)
        if any(imported.values()):
            log.warning("imported %s from %s into PostgreSQL; the file is no longer used", imported, runtime_db)
    return stores


def _rows(path: Path, sql: str) -> list[sqlite3.Row]:
    con = sqlite3.connect(path)
    try:
        con.row_factory = sqlite3.Row
        return con.execute(sql).fetchall()
    except sqlite3.OperationalError:  # table absent: nothing to import
        return []
    finally:
        con.close()


def import_sqlite(path: Path, db: _Connections, outbox: PostgresOutbox, node: str) -> dict[str, int]:
    counts = {"outbox": outbox.import_sqlite(path), "task_commits": 0, "deployment_evidence": 0,
              "operating_metrics": 0, "runtime_health": 0}
    con = db.get()
    with con.transaction():
        for r in _rows(path, "SELECT * FROM task_commits"):
            counts["task_commits"] += con.execute(
                "INSERT INTO task_commits (task_id, trace_id, status, result, committed_at) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (task_id) DO NOTHING",
                (r["task_id"], r["trace_id"], r["status"], db.jsonb(json.loads(r["result_json"])),
                 r["committed_at"])).rowcount
        if con.execute("SELECT NOT EXISTS (SELECT 1 FROM deployment_evidence)").fetchone()[0]:
            for r in _rows(path, "SELECT * FROM deployment_evidence ORDER BY id"):
                con.execute("INSERT INTO deployment_evidence (variant_id, phase, payload, created_at) "
                            "VALUES (%s, %s, %s, %s)",
                            (r["variant_id"], r["phase"], db.jsonb(json.loads(r["payload_json"])), r["created_at"]))
                counts["deployment_evidence"] += 1
        if con.execute("SELECT NOT EXISTS (SELECT 1 FROM operating_metrics)").fetchone()[0]:
            for r in _rows(path, "SELECT * FROM operating_metrics ORDER BY id"):
                con.execute("INSERT INTO operating_metrics (node, captured_at, payload) VALUES (%s, %s, %s)",
                            (node, r["captured_at"], db.jsonb(json.loads(r["payload_json"]))))
                counts["operating_metrics"] += 1
        if con.execute("SELECT NOT EXISTS (SELECT 1 FROM runtime_health WHERE node = %s)", (node,)).fetchone()[0]:
            for r in _rows(path, "SELECT * FROM runtime_health"):
                con.execute(
                    "INSERT INTO runtime_health (node, variant_id, state, failures, failure_threshold, "
                    "recovery_seconds, opened_at_wall, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (node, r["variant_id"], r["state"], r["failures"], r["failure_threshold"], r["recovery_seconds"],
                     r["opened_at_wall"], r["updated_at"]))
                counts["runtime_health"] += 1
    return counts
