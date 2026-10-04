# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from hydra.registry.circuit_breaker import Breaker as CircuitBreaker
from hydra.registry.circuit_breaker import CircuitState
from hydra.core.runtime_paths import runtime_path


class RuntimeHealthStore:
    def __init__(self, path: str | Path = runtime_path("hydra.db")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_health (
                    variant_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    failures INTEGER NOT NULL,
                    failure_threshold INTEGER NOT NULL,
                    recovery_seconds REAL NOT NULL,
                    opened_at_wall REAL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, variant_id: str, breaker: CircuitBreaker) -> None:
        opened_at_wall = None
        if breaker.opened_at is not None:
            age_seconds = max(monotonic() - breaker.opened_at, 0.0)
            opened_at_wall = datetime.now(UTC).timestamp() - age_seconds

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_health (
                    variant_id, state, failures, failure_threshold,
                    recovery_seconds, opened_at_wall, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(variant_id) DO UPDATE SET
                    state = excluded.state,
                    failures = excluded.failures,
                    failure_threshold = excluded.failure_threshold,
                    recovery_seconds = excluded.recovery_seconds,
                    opened_at_wall = excluded.opened_at_wall,
                    updated_at = excluded.updated_at
                """,
                (
                    variant_id,
                    breaker.state.value,
                    breaker.failures,
                    breaker.failure_threshold,
                    breaker.recovery_seconds,
                    opened_at_wall,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def load(self) -> dict[str, CircuitBreaker]:
        restored: dict[str, CircuitBreaker] = {}
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM runtime_health").fetchall()

        now_wall = datetime.now(UTC).timestamp()
        now_mono = monotonic()
        for row in rows:
            breaker = CircuitBreaker(
                failure_threshold=row["failure_threshold"],
                recovery_seconds=row["recovery_seconds"],
                state=CircuitState(row["state"]),
                failures=row["failures"],
            )
            opened_at_wall = row["opened_at_wall"]
            if opened_at_wall is not None:
                elapsed = max(now_wall - float(opened_at_wall), 0.0)
                breaker.opened_at = now_mono - elapsed
            restored[row["variant_id"]] = breaker
        return restored
