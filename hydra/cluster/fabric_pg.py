# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""PostgreSQL Execution Fabric: the ``WorkQueue`` contract shared by every gateway and worker node.

Same semantics as the SQLite queue (priorities, leases, retries with backoff, dead letters,
idempotency, checkpoints, no background work while interactive work waits), but safe with many
concurrent consumers on many hosts:

* claims lock rows with ``FOR UPDATE SKIP LOCKED`` (a job is leased by exactly one worker);
* submissions with the same idempotency key are serialised with a transaction advisory lock;
* every state change is one transaction, so a crash never leaves a half-updated job.

Requires ``psycopg`` 3 (``pip install "hydra-engine[postgres]"``)."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from hydra.cluster.fabric import Priority, WorkItem

FABRIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS fabric_work (
    id            TEXT PRIMARY KEY,
    capability    TEXT NOT NULL,
    priority      INTEGER NOT NULL,
    status        TEXT NOT NULL,
    available_at  DOUBLE PRECISION NOT NULL,
    lease_expires DOUBLE PRECISION,
    idem          TEXT NOT NULL,
    body          JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS fabric_work_claim ON fabric_work (status, capability, priority, available_at);
CREATE INDEX IF NOT EXISTS fabric_work_open_idem ON fabric_work (idem) WHERE status IN ('queued', 'leased');
CREATE TABLE IF NOT EXISTS fabric_idempotency (
    key    TEXT PRIMARY KEY,
    result JSONB NOT NULL,
    at     DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS fabric_checkpoints (
    task_id TEXT NOT NULL,
    step    INTEGER NOT NULL,
    state   JSONB NOT NULL,
    at      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (task_id, step)
);
"""

_UPSERT = """
INSERT INTO fabric_work (id, capability, priority, status, available_at, lease_expires, idem, body)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET capability = EXCLUDED.capability, priority = EXCLUDED.priority,
    status = EXCLUDED.status, available_at = EXCLUDED.available_at,
    lease_expires = EXCLUDED.lease_expires, idem = EXCLUDED.idem, body = EXCLUDED.body
"""


class PostgresWorkQueue:
    backend = "postgres"

    def __init__(self, url: str) -> None:
        import psycopg  # optional dependency

        self._psycopg = psycopg
        self.url = url
        self._local = threading.local()
        with self._con().transaction():
            self._con().execute(FABRIC_SCHEMA)

    # ------------------------------------------------------------------ plumbing
    def _con(self):
        con = getattr(self._local, "con", None)
        if con is None or con.closed:
            con = self._psycopg.connect(self.url, autocommit=True)
            self._local.con = con
        return con

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None and not con.closed:
            con.close()

    @staticmethod
    def _load(body: Any) -> WorkItem:
        return WorkItem.model_validate(body if isinstance(body, dict) else json.loads(body))

    def _save(self, con, w: WorkItem) -> None:
        con.execute(_UPSERT, (w.id, w.capability, int(w.priority), w.status, w.available_at, w.lease_expires,
                              w.idempotency_key, w.model_dump_json()))

    def _locked(self, con, item_id: str) -> WorkItem | None:
        row = con.execute("SELECT body FROM fabric_work WHERE id = %s FOR UPDATE", (item_id,)).fetchone()
        return self._load(row[0]) if row else None

    # ------------------------------------------------------------------ producer
    def submit(self, item: WorkItem) -> WorkItem:
        if not item.idempotency_key:
            item.idempotency_key = item.id
        con = self._con()
        with con.transaction():
            con.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (item.idempotency_key,))
            done = con.execute("SELECT result FROM fabric_idempotency WHERE key = %s",
                               (item.idempotency_key,)).fetchone()
            if done:
                item.status, item.result = "done", done[0]
                return item
            existing = con.execute("SELECT body FROM fabric_work WHERE idem = %s AND status IN ('queued', 'leased') "
                                   "LIMIT 1", (item.idempotency_key,)).fetchone()
            if existing:
                return self._load(existing[0])
            self._save(con, item)
        return item

    def get(self, item_id: str) -> WorkItem | None:
        row = self._con().execute("SELECT body FROM fabric_work WHERE id = %s", (item_id,)).fetchone()
        return self._load(row[0]) if row else None

    # ------------------------------------------------------------------ consumer
    def claim(self, capabilities: list[str], owner: str, lease_s: float = 30.0,
              allow_background_when_busy: bool = False) -> WorkItem | None:
        now = time.time()
        con = self._con()
        with con.transaction():
            # Recover expired leases (rows another worker is recovering right now are skipped).
            for (body,) in con.execute("SELECT body FROM fabric_work WHERE status = 'leased' AND lease_expires < %s "
                                       "FOR UPDATE SKIP LOCKED", (now,)).fetchall():
                w = self._load(body)
                w.status = "queued" if w.attempts < w.max_attempts else "dead"
                w.lease_owner, w.lease_expires = None, None
                w.error = (w.error or "") + " | lease expired"
                self._save(con, w)
            interactive_waiting = con.execute(
                "SELECT EXISTS (SELECT 1 FROM fabric_work WHERE status = 'queued' AND priority <= %s "
                "AND available_at <= %s)", (int(Priority.INTERACTIVE), now)).fetchone()[0]
            max_pri = int(Priority.BACKGROUND_LAB) if (allow_background_when_busy or not interactive_waiting) \
                else int(Priority.BATCH)
            row = con.execute("SELECT body FROM fabric_work WHERE status = 'queued' AND capability = ANY(%s) "
                              "AND available_at <= %s AND priority <= %s ORDER BY priority, available_at "
                              "LIMIT 1 FOR UPDATE SKIP LOCKED", (list(capabilities), now, max_pri)).fetchone()
            if not row:
                return None
            w = self._load(row[0])
            w.status, w.lease_owner, w.lease_expires = "leased", owner, now + lease_s
            w.attempts += 1
            self._save(con, w)
            return w

    def renew(self, item_id: str, owner: str, lease_s: float = 30.0) -> bool:
        con = self._con()
        with con.transaction():
            w = self._locked(con, item_id)
            if w is None or w.status != "leased" or w.lease_owner != owner:
                return False
            w.lease_expires = time.time() + lease_s
            self._save(con, w)
            return True

    def complete(self, item_id: str, owner: str, result: dict[str, Any]) -> bool:
        con = self._con()
        with con.transaction():
            w = self._locked(con, item_id)
            if w is None or w.lease_owner != owner:
                return False
            w.status, w.result, w.lease_owner, w.lease_expires = "done", result, None, None
            self._save(con, w)
            con.execute("INSERT INTO fabric_idempotency (key, result, at) VALUES (%s, %s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET result = EXCLUDED.result, at = EXCLUDED.at",
                        (w.idempotency_key, json.dumps(result, default=str), time.time()))
            return True

    def fail(self, item_id: str, owner: str, error: str, retry_in_s: float = 2.0) -> WorkItem | None:
        con = self._con()
        with con.transaction():
            w = self._locked(con, item_id)
            if w is None or w.lease_owner != owner:
                return None
            w.error = error[:1000]
            w.lease_owner, w.lease_expires = None, None
            if w.attempts >= w.max_attempts:
                w.status = "dead"
            else:
                w.status = "queued"
                w.available_at = time.time() + retry_in_s * (2 ** (w.attempts - 1))
            self._save(con, w)
            return w

    def idempotent_result(self, key: str) -> dict[str, Any] | None:
        row = self._con().execute("SELECT result FROM fabric_idempotency WHERE key = %s", (key,)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ checkpoints
    def checkpoint(self, task_id: str, step: int, state: dict[str, Any]) -> None:
        self._con().execute("INSERT INTO fabric_checkpoints (task_id, step, state, at) VALUES (%s, %s, %s, %s) "
                            "ON CONFLICT (task_id, step) DO UPDATE SET state = EXCLUDED.state, at = EXCLUDED.at",
                            (task_id, step, json.dumps(state, default=str), time.time()))

    def last_checkpoint(self, task_id: str) -> tuple[int, dict[str, Any]] | None:
        row = self._con().execute("SELECT step, state FROM fabric_checkpoints WHERE task_id = %s "
                                  "ORDER BY step DESC LIMIT 1", (task_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def stats(self) -> dict[str, Any]:
        rows = self._con().execute("SELECT status, priority, COUNT(*) FROM fabric_work "
                                   "GROUP BY status, priority").fetchall()
        out: dict[str, dict[str, int]] = {}
        for st, pr, n in rows:
            out.setdefault(st, {})[Priority(pr).name] = n
        return out
