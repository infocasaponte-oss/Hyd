# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from hydra.core.runtime_paths import runtime_path


@dataclass(frozen=True)
class OutboxMessage:
    id: UUID
    topic: str
    aggregate_id: UUID
    trace_id: str
    payload: dict[str, Any]
    created_at: str
    published_at: str | None = None
    attempts: int = 0
    next_attempt_at: str | None = None
    last_error: str | None = None
    dead_lettered_at: str | None = None


class TransactionalOutbox:
    backend = "sqlite"

    def __init__(self, path: str | Path = runtime_path("hydra.db")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    published_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    dead_lettered_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
                    ON outbox(published_at, created_at);
                """
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def enqueue(
        self,
        connection: sqlite3.Connection,
        *,
        topic: str,
        aggregate_id: UUID,
        trace_id: str,
        payload: dict[str, Any],
    ) -> OutboxMessage:
        message = OutboxMessage(
            id=uuid4(),
            topic=topic,
            aggregate_id=aggregate_id,
            trace_id=trace_id,
            payload=payload,
            created_at=datetime.now(UTC).isoformat(),
        )
        connection.execute(
            """
            INSERT INTO outbox (
                id, topic, aggregate_id, trace_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(message.id),
                message.topic,
                str(message.aggregate_id),
                message.trace_id,
                json.dumps(message.payload, sort_keys=True),
                message.created_at,
            ),
        )
        return message

    def pending(self, limit: int = 100) -> list[OutboxMessage]:
        with self._connect() as connection:
            now = datetime.now(UTC).isoformat()
            rows = connection.execute(
                """
                SELECT * FROM outbox
                WHERE published_at IS NULL
                  AND dead_lettered_at IS NULL
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY created_at, rowid
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def mark_published(self, message_id: UUID) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE outbox
                SET published_at = ?, last_error = NULL, next_attempt_at = NULL
                WHERE id = ?
                """,
                (datetime.now(UTC).isoformat(), str(message_id)),
            )

    def record_failure(
        self,
        message_id: UUID,
        *,
        error: str,
        next_attempt_at: str | None,
        dead_letter: bool,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE outbox
                SET attempts = attempts + 1,
                    last_error = ?,
                    next_attempt_at = ?,
                    dead_lettered_at = CASE WHEN ? THEN ? ELSE dead_lettered_at END
                WHERE id = ?
                """,
                (
                    error[:2000],
                    next_attempt_at,
                    1 if dead_letter else 0,
                    datetime.now(UTC).isoformat() if dead_letter else None,
                    str(message_id),
                ),
            )

    def requeue_dead_letter(self, message_id: UUID) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE outbox
                SET dead_lettered_at = NULL,
                    next_attempt_at = NULL,
                    last_error = NULL,
                    attempts = 0
                WHERE id = ?
                  AND dead_lettered_at IS NOT NULL
                  AND published_at IS NULL
                """,
                (str(message_id),),
            )
            return cursor.rowcount == 1

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            pending, dead = connection.execute(
                """
                SELECT
                    COALESCE(SUM(published_at IS NULL AND dead_lettered_at IS NULL), 0),
                    COALESCE(SUM(dead_lettered_at IS NOT NULL), 0)
                FROM outbox
                """
            ).fetchone()
        return {"pending": pending, "dead_letters": dead}

    def pending_summary(self) -> tuple[int, int, str | None]:
        """(pending, dead letters, created_at of the oldest pending message), counted in the database."""
        with self._connect() as connection:
            pending, dead, oldest = connection.execute(
                """
                SELECT
                    COALESCE(SUM(published_at IS NULL AND dead_lettered_at IS NULL), 0),
                    COALESCE(SUM(dead_lettered_at IS NOT NULL), 0),
                    MIN(CASE WHEN published_at IS NULL AND dead_lettered_at IS NULL THEN created_at END)
                FROM outbox
                """
            ).fetchone()
        return pending, dead, oldest

    def dead_letters(self, limit: int = 100) -> list[OutboxMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox
                WHERE dead_lettered_at IS NOT NULL
                ORDER BY dead_lettered_at, id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> OutboxMessage:
        return OutboxMessage(
            id=UUID(row["id"]),
            topic=row["topic"],
            aggregate_id=UUID(row["aggregate_id"]),
            trace_id=row["trace_id"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
            published_at=row["published_at"],
            attempts=row["attempts"],
            next_attempt_at=row["next_attempt_at"],
            last_error=row["last_error"],
            dead_lettered_at=row["dead_lettered_at"],
        )
