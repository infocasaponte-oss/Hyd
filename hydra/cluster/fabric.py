# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Execution Fabric: durable priority queues with leases, idempotency and checkpoints.

    REALTIME > INTERACTIVE > NORMAL > BATCH > BACKGROUND_LAB

* A worker *claims* a job with a lease (e.g. 30 s) and renews it while working; if it dies
  the lease expires and another worker picks the job up (automatic recovery).
* Every job has an ``idempotency_key``: a re-delivered job whose effect already happened
  returns the stored result instead of executing a dangerous action twice.
* Long tasks checkpoint after each step and resume from the last one.
* Lab/batch work never starves production: background jobs are not handed out while
  interactive work is waiting (preemption at the queue level).

SQLite (WAL) gives durability for one host. With PostgreSQL configured the same contract runs on
``hydra.cluster.fabric_pg.PostgresWorkQueue`` and is shared by every gateway and worker node
(``open_work_queue`` picks the backend; ``HYDRA_FABRIC_BACKEND`` = auto | sqlite | postgres)."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import sqlite3
import threading
import time
import uuid
from enum import IntEnum
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

log = logging.getLogger("hydra.fabric")


class Priority(IntEnum):
    REALTIME = 0
    INTERACTIVE = 1
    NORMAL = 2
    BATCH = 3
    BACKGROUND_LAB = 4

    @classmethod
    def parse(cls, v: str | int) -> Priority:
        return cls(v) if isinstance(v, int) else cls[str(v).upper()]


class WorkItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str = ""
    type: str = "inference"
    capability: str = "reasoning"
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Priority.NORMAL
    timeout_ms: int = 120_000
    idempotency_key: str = ""
    required_resources: dict[str, Any] = Field(default_factory=dict)
    status: str = "queued"  # queued | leased | done | failed | dead
    attempts: int = 0
    max_attempts: int = 3
    lease_owner: str | None = None
    lease_expires: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = Field(default_factory=time.time)
    available_at: float = Field(default_factory=time.time)


SCHEMA = """
CREATE TABLE IF NOT EXISTS work (id TEXT PRIMARY KEY, capability TEXT, priority INT, status TEXT,
  available_at REAL, lease_expires REAL, idem TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS work_claim ON work(status, capability, priority, available_at);
CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, result TEXT, at REAL);
CREATE TABLE IF NOT EXISTS checkpoints (task_id TEXT, step INT, state TEXT, at REAL, PRIMARY KEY(task_id, step));
"""


class WorkQueue:
    backend = "sqlite"

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._local = threading.local()
        self._lock = threading.Lock()
        with self._con() as c:
            c.executescript(SCHEMA)

    def _con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            con.execute("PRAGMA journal_mode=WAL")
            self._local.con = con
        return con

    def _save(self, c: sqlite3.Connection, w: WorkItem) -> None:
        c.execute("INSERT OR REPLACE INTO work VALUES (?,?,?,?,?,?,?,?)",
                  (w.id, w.capability, int(w.priority), w.status, w.available_at, w.lease_expires,
                   w.idempotency_key, w.model_dump_json()))

    # ------------------------------------------------------------------ producer
    def submit(self, item: WorkItem) -> WorkItem:
        if not item.idempotency_key:
            item.idempotency_key = item.id
        with self._lock:
            c = self._con()
            done = c.execute("SELECT result FROM idempotency WHERE key=?", (item.idempotency_key,)).fetchone()
            if done:
                item.status, item.result = "done", json.loads(done[0])
                return item
            existing = c.execute("SELECT body FROM work WHERE idem=? AND status IN ('queued','leased')",
                                 (item.idempotency_key,)).fetchone()
            if existing:
                return WorkItem.model_validate_json(existing[0])
            self._save(c, item)
        return item

    def get(self, item_id: str) -> WorkItem | None:
        row = self._con().execute("SELECT body FROM work WHERE id=?", (item_id,)).fetchone()
        return WorkItem.model_validate_json(row[0]) if row else None

    # ------------------------------------------------------------------ consumer
    def claim(self, capabilities: list[str], owner: str, lease_s: float = 30.0,
              allow_background_when_busy: bool = False) -> WorkItem | None:
        now = time.time()
        with self._lock:
            c = self._con()
            c.execute("BEGIN IMMEDIATE")
            try:
                # recover expired leases first
                for (body,) in c.execute("SELECT body FROM work WHERE status='leased' AND lease_expires < ?",
                                         (now,)).fetchall():
                    w = WorkItem.model_validate_json(body)
                    w.status = "queued" if w.attempts < w.max_attempts else "dead"
                    w.lease_owner, w.lease_expires = None, None
                    w.error = (w.error or "") + " | lease expired"
                    self._save(c, w)
                marks = ",".join("?" * len(capabilities))
                interactive_waiting = c.execute(
                    "SELECT COUNT(*) FROM work WHERE status='queued' AND priority<=? AND available_at<=?",
                    (int(Priority.INTERACTIVE), now)).fetchone()[0]
                max_pri = int(Priority.BACKGROUND_LAB) if (allow_background_when_busy or not interactive_waiting) \
                    else int(Priority.BATCH)
                row = c.execute(f"SELECT body FROM work WHERE status='queued' AND capability IN ({marks}) "
                                f"AND available_at<=? AND priority<=? ORDER BY priority, available_at LIMIT 1",
                                (*capabilities, now, max_pri)).fetchone()
                if not row:
                    c.execute("COMMIT")
                    return None
                w = WorkItem.model_validate_json(row[0])
                w.status, w.lease_owner, w.lease_expires = "leased", owner, now + lease_s
                w.attempts += 1
                self._save(c, w)
                c.execute("COMMIT")
                return w
            except Exception:
                c.execute("ROLLBACK")
                raise

    def renew(self, item_id: str, owner: str, lease_s: float = 30.0) -> bool:
        with self._lock:
            c = self._con()
            w = self.get(item_id)
            if w is None or w.status != "leased" or w.lease_owner != owner:
                return False
            w.lease_expires = time.time() + lease_s
            self._save(c, w)
            return True

    def complete(self, item_id: str, owner: str, result: dict[str, Any]) -> bool:
        with self._lock:
            c = self._con()
            w = self.get(item_id)
            if w is None or w.lease_owner != owner:
                return False
            w.status, w.result, w.lease_owner, w.lease_expires = "done", result, None, None
            self._save(c, w)
            c.execute("INSERT OR REPLACE INTO idempotency VALUES (?,?,?)",
                      (w.idempotency_key, json.dumps(result, default=str), time.time()))
            return True

    def fail(self, item_id: str, owner: str, error: str, retry_in_s: float = 2.0) -> WorkItem | None:
        with self._lock:
            c = self._con()
            w = self.get(item_id)
            if w is None or w.lease_owner != owner:
                return None
            w.error = error[:1000]
            w.lease_owner, w.lease_expires = None, None
            if w.attempts >= w.max_attempts:
                w.status = "dead"
            else:
                w.status = "queued"
                w.available_at = time.time() + retry_in_s * (2 ** (w.attempts - 1))
            self._save(c, w)
            return w

    def idempotent_result(self, key: str) -> dict[str, Any] | None:
        row = self._con().execute("SELECT result FROM idempotency WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    # ------------------------------------------------------------------ checkpoints
    def checkpoint(self, task_id: str, step: int, state: dict[str, Any]) -> None:
        self._con().execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?)",
                            (task_id, step, json.dumps(state, default=str), time.time()))

    def last_checkpoint(self, task_id: str) -> tuple[int, dict[str, Any]] | None:
        row = self._con().execute("SELECT step, state FROM checkpoints WHERE task_id=? ORDER BY step DESC LIMIT 1",
                                  (task_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def stats(self) -> dict[str, Any]:
        rows = self._con().execute("SELECT status, priority, COUNT(*) FROM work GROUP BY status, priority").fetchall()
        out: dict[str, dict[str, int]] = {}
        for st, pr, n in rows:
            out.setdefault(st, {})[Priority(pr).name] = n
        return out


def open_work_queue(backend: str, path: Path, postgres_url: str = ""):
    """The fabric queue for this node: PostgreSQL (shared by every node) or SQLite (this host only)."""
    if backend not in ("auto", "sqlite", "postgres"):
        raise ValueError(f"unknown fabric backend {backend!r}; use auto, sqlite or postgres")
    if backend == "postgres" and not postgres_url:
        raise ValueError("HYDRA_FABRIC_BACKEND=postgres requires HYDRA_POSTGRES_URL")
    if backend != "sqlite" and postgres_url:
        try:
            from hydra.cluster.fabric_pg import PostgresWorkQueue

            return PostgresWorkQueue(postgres_url)
        except ImportError:
            if backend == "postgres":
                raise RuntimeError('the PostgreSQL fabric needs psycopg: pip install "hydra-engine[postgres]"') from None
            log.warning("HYDRA_POSTGRES_URL is set but psycopg is not installed: the fabric queue is local "
                        "SQLite and is NOT shared with other nodes")
    return WorkQueue(path)


Handler = Callable[[WorkItem], Awaitable[dict[str, Any]]]


async def run_fabric_worker(queue: WorkQueue, capabilities: list[str], handler: Handler, *,
                            owner: str | None = None, lease_s: float = 30.0, poll_s: float = 0.5,
                            once: bool = False, stop: asyncio.Event | None = None) -> int:
    """Consume structured work (no agents 'chatting'): claim -> renew while running -> complete/fail."""
    owner = owner or f"{socket.gethostname()}:{uuid.uuid4().hex[:6]}"
    processed = 0
    while not (stop and stop.is_set()):
        item = await asyncio.to_thread(queue.claim, capabilities, owner, lease_s)
        if item is None:
            if once:
                return processed
            await asyncio.sleep(poll_s)
            continue
        if (prev := queue.idempotent_result(item.idempotency_key)) is not None:
            queue.complete(item.id, owner, prev)
            processed += 1
            continue

        async def keepalive():
            while True:
                await asyncio.sleep(lease_s / 3)
                queue.renew(item.id, owner, lease_s)
        ka = asyncio.create_task(keepalive())
        try:
            result = await asyncio.wait_for(handler(item), timeout=item.timeout_ms / 1000)
            queue.complete(item.id, owner, result)
        except Exception as exc:
            queue.fail(item.id, owner, f"{type(exc).__name__}: {exc}")
        finally:
            ka.cancel()
        processed += 1
        if once:
            return processed
    return processed
