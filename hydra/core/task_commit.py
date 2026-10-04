# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from hydra.core.outbox import TransactionalOutbox
from hydra.core.runtime_paths import runtime_path


@dataclass(frozen=True)
class TaskCommit:
    task_id: UUID
    trace_id: str
    status: str
    result: dict[str, Any]


class CaptureUnitOfWork:
    def __init__(self, path: str | Path = runtime_path("hydra.db")):
        self.outbox = TransactionalOutbox(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return self.outbox._connect()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_commits (
                    task_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    committed_at TEXT NOT NULL
                )
                """
            )

    def commit_terminal(
        self,
        commit: TaskCommit,
        *,
        event_payload: dict[str, Any],
        provenance_payload: dict[str, Any],
        corpus_payload: dict[str, Any] | None = None,
    ) -> None:
        with self.outbox.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO task_commits (
                    task_id, trace_id, status, result_json, committed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(commit.task_id),
                    commit.trace_id,
                    commit.status,
                    json.dumps(commit.result, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.outbox.enqueue(
                connection,
                topic="event",
                aggregate_id=commit.task_id,
                trace_id=commit.trace_id,
                payload=event_payload,
            )
            self.outbox.enqueue(
                connection,
                topic="provenance",
                aggregate_id=commit.task_id,
                trace_id=commit.trace_id,
                payload=provenance_payload,
            )
            if corpus_payload is not None:
                self.outbox.enqueue(
                    connection,
                    topic="corpus",
                    aggregate_id=commit.task_id,
                    trace_id=commit.trace_id,
                    payload=corpus_payload,
                )

    def get_task_commit(self, task_id: UUID) -> TaskCommit | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_commits WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
        if row is None:
            return None
        return TaskCommit(
            task_id=UUID(row["task_id"]),
            trace_id=row["trace_id"],
            status=row["status"],
            result=json.loads(row["result_json"]),
        )
