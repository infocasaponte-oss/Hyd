# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""PostgreSQL store for the capture outbox, shared by every node.

Same interface as ``hydra.runtime.outbox.TransactionalOutbox`` (``transaction``, ``enqueue``,
``pending``, ``mark_published``, ``record_failure``, ``requeue_dead_letter``, ``dead_letters``,
``counts``) on the ``capture_outbox`` table. ``pending`` *claims* the messages it returns: they are
locked with ``FOR UPDATE SKIP LOCKED`` and leased for ``lease_s`` seconds, so two nodes never retry
the same deferred write at once (a ledger event would be appended twice). A node that dies mid-batch
releases its messages when the lease expires. Requires ``psycopg`` 3."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from hydra.core.outbox import OutboxMessage, TransactionalOutbox

log = logging.getLogger("hydra.capture")

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    id               UUID PRIMARY KEY,
    topic            TEXT NOT NULL,
    aggregate_id     UUID NOT NULL,
    trace_id         TEXT NOT NULL,
    payload          JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    published_at     TIMESTAMPTZ,
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ,
    last_error       TEXT,
    dead_lettered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS {table}_due ON {table} (next_attempt_at, created_at)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL;
"""
TABLES = ("capture_outbox", "runtime_outbox")  # platform capture writes; runtime-line transactional outbox

_COLUMNS = ("id, topic, aggregate_id, trace_id, payload, created_at, published_at, attempts, next_attempt_at, "
            "last_error, dead_lettered_at")


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _message(row) -> OutboxMessage:
    (mid, topic, aggregate, trace, payload, created, published, attempts, next_at, error, dead) = row
    return OutboxMessage(id=UUID(str(mid)), topic=topic, aggregate_id=UUID(str(aggregate)), trace_id=trace,
                         payload=payload if isinstance(payload, dict) else json.loads(payload),
                         created_at=_iso(created), published_at=_iso(published), attempts=attempts,
                         next_attempt_at=_iso(next_at), last_error=error, dead_lettered_at=_iso(dead))


class PostgresOutbox:
    backend = "postgres"

    def __init__(self, url: str, lease_s: float = 120.0, table: str = "capture_outbox") -> None:
        """``table``: ``capture_outbox`` (platform capture) or ``runtime_outbox`` (runtime line)."""
        import psycopg  # optional dependency
        from psycopg.types.json import Jsonb

        if table not in TABLES:
            raise ValueError(f"unknown outbox table {table!r}")
        self._psycopg, self._jsonb = psycopg, Jsonb
        self.url = url
        self.table = table
        self.lease_s = lease_s
        self._local = threading.local()
        con = self._con()
        with con.transaction():
            con.execute(OUTBOX_SCHEMA.format(table=table))

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

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        con = self._con()
        with con.transaction():
            yield con

    def enqueue(self, connection, *, topic: str, aggregate_id: UUID, trace_id: str,
                payload: dict[str, Any]) -> OutboxMessage:
        message = OutboxMessage(id=uuid4(), topic=topic, aggregate_id=aggregate_id, trace_id=trace_id,
                                payload=payload, created_at=datetime.now(UTC).isoformat())
        connection.execute(f"INSERT INTO {self.table} (id, topic, aggregate_id, trace_id, payload, created_at) "
                           "VALUES (%s, %s, %s, %s, %s, %s)",
                           (message.id, topic, aggregate_id, trace_id, self._jsonb(payload), message.created_at))
        return message

    def pending(self, limit: int = 100) -> list[OutboxMessage]:
        """Claim up to ``limit`` due messages for ``lease_s`` seconds (see the module docstring)."""
        lease_until = datetime.now(UTC) + timedelta(seconds=self.lease_s)
        rows = self._con().execute(
            f"""UPDATE {self.table} SET next_attempt_at = %s
                WHERE id IN (SELECT id FROM {self.table}
                             WHERE published_at IS NULL AND dead_lettered_at IS NULL
                               AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                             ORDER BY created_at, id LIMIT %s FOR UPDATE SKIP LOCKED)
                RETURNING {_COLUMNS}""", (lease_until, limit)).fetchall()
        return sorted((_message(r) for r in rows), key=lambda m: (m.created_at, str(m.id)))

    def mark_published(self, message_id: UUID) -> None:
        self._con().execute(f"UPDATE {self.table} SET published_at = now(), last_error = NULL, "
                            "next_attempt_at = NULL WHERE id = %s", (message_id,))

    def record_failure(self, message_id: UUID, *, error: str, next_attempt_at: str | None,
                       dead_letter: bool) -> None:
        self._con().execute(
            f"UPDATE {self.table} SET attempts = attempts + 1, last_error = %s, next_attempt_at = %s, "
            "dead_lettered_at = CASE WHEN %s THEN now() ELSE dead_lettered_at END WHERE id = %s",
            (error[:2000], next_attempt_at, dead_letter, message_id))

    def requeue_dead_letter(self, message_id: UUID) -> bool:
        cur = self._con().execute(
            f"UPDATE {self.table} SET dead_lettered_at = NULL, next_attempt_at = NULL, last_error = NULL, "
            "attempts = 0 WHERE id = %s AND dead_lettered_at IS NOT NULL AND published_at IS NULL", (message_id,))
        return cur.rowcount == 1

    def dead_letters(self, limit: int = 100) -> list[OutboxMessage]:
        rows = self._con().execute(f"SELECT {_COLUMNS} FROM {self.table} WHERE dead_lettered_at IS NOT NULL "
                                   "ORDER BY dead_lettered_at, id LIMIT %s", (limit,)).fetchall()
        return [_message(r) for r in rows]

    def counts(self) -> dict[str, int]:
        pending, dead = self._con().execute(
            "SELECT count(*) FILTER (WHERE published_at IS NULL AND dead_lettered_at IS NULL), "
            f"count(*) FILTER (WHERE dead_lettered_at IS NOT NULL) FROM {self.table}").fetchone()
        return {"pending": pending, "dead_letters": dead}

    def pending_summary(self) -> tuple[int, int, str | None]:
        """(pending, dead letters, created_at of the oldest pending message), without claiming anything."""
        pending, dead, oldest = self._con().execute(
            "SELECT count(*) FILTER (WHERE published_at IS NULL AND dead_lettered_at IS NULL), "
            "count(*) FILTER (WHERE dead_lettered_at IS NOT NULL), "
            f"min(created_at) FILTER (WHERE published_at IS NULL AND dead_lettered_at IS NULL) FROM {self.table}"
        ).fetchone()
        return pending, dead, _iso(oldest)

    def import_sqlite(self, path: Path) -> int:
        """Copy the unpublished messages of a local SQLite capture outbox (kept as is) once, by id."""
        con = sqlite3.connect(path)
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT * FROM outbox WHERE published_at IS NULL").fetchall()
        except sqlite3.OperationalError:
            return 0
        finally:
            con.close()
        imported = 0
        with self.transaction() as pg:
            for r in rows:
                cur = pg.execute(
                    f"INSERT INTO {self.table} (id, topic, aggregate_id, trace_id, payload, created_at, attempts, "
                    "next_attempt_at, last_error, dead_lettered_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (r["id"], r["topic"], r["aggregate_id"], r["trace_id"], self._jsonb(json.loads(r["payload_json"])),
                     r["created_at"], r["attempts"], r["next_attempt_at"], r["last_error"], r["dead_lettered_at"]))
                imported += cur.rowcount
        return imported


def open_outbox_store(backend: str, path: Path, postgres_url: str = "") -> TransactionalOutbox | PostgresOutbox:
    """``backend``: auto (PostgreSQL when ``postgres_url`` is set and psycopg is installed) | sqlite | postgres.
    A PostgreSQL store imports the unpublished messages of an existing SQLite outbox once."""
    if backend not in ("auto", "sqlite", "postgres"):
        raise ValueError(f"unknown HYDRA_OUTBOX_BACKEND {backend!r}; use auto, sqlite or postgres")
    if backend == "postgres" and not postgres_url:
        raise ValueError("HYDRA_OUTBOX_BACKEND=postgres requires HYDRA_POSTGRES_URL")
    if backend != "sqlite" and postgres_url:
        try:
            store = PostgresOutbox(postgres_url)
        except ImportError:
            if backend == "postgres":
                raise RuntimeError('the PostgreSQL capture outbox needs psycopg: pip install "hydra-engine[postgres]"') \
                    from None
            log.warning("HYDRA_POSTGRES_URL is set but psycopg is not installed: the capture outbox stays in local "
                        "SQLite and is NOT shared with other nodes")
        else:
            if Path(path).exists():
                imported = store.import_sqlite(Path(path))
                if imported:
                    log.warning("imported %d unpublished capture outbox messages from %s into PostgreSQL; the file "
                                "is no longer used", imported, path)
            return store
    return TransactionalOutbox(path)
