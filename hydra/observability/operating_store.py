# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Operating metrics snapshots (SQLite; ``hydra.core.native_stores`` has the PostgreSQL version)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from hydra.observability.operating import OperatingMetrics
from hydra.core.runtime_paths import runtime_path


class OperatingMetricsStore:
    def __init__(
        self,
        path: str | Path = runtime_path("hydra.db"),
        *,
        max_snapshots: int = 10_000,
    ):
        if max_snapshots < 1:
            raise ValueError("max_snapshots must be positive")
        self.path = Path(path)
        self.max_snapshots = max_snapshots
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operating_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_operating_metrics_captured
                    ON operating_metrics(captured_at, id);
                """
            )

    def append(self, metrics: OperatingMetrics) -> int:
        captured_at = datetime.now(UTC).isoformat()
        payload = json.dumps(asdict(metrics), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO operating_metrics (captured_at, payload_json)
                VALUES (?, ?)
                """,
                (captured_at, payload),
            )
            snapshot_id = int(cursor.lastrowid)
            connection.execute(
                """
                DELETE FROM operating_metrics
                WHERE id NOT IN (
                    SELECT id
                    FROM operating_metrics
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (self.max_snapshots,),
            )
            return snapshot_id

    def recent(self, limit: int = 100) -> list[dict]:
        if limit < 1 or limit > 1000:
            raise ValueError("Metrics history limit must be between 1 and 1000")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, captured_at, payload_json
                FROM operating_metrics
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "captured_at": row["captured_at"],
                "metrics": json.loads(row["payload_json"]),
            }
            for row in rows
        ]
