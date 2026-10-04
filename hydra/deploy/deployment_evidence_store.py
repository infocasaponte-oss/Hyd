# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from hydra.deploy.deployment_evidence import CanaryEvidence, ShadowEvidence
from hydra.core.runtime_paths import runtime_path


class DeploymentEvidenceStore:
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS deployment_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    variant_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_deployment_evidence_variant_phase
                    ON deployment_evidence(variant_id, phase, id);
                """
            )

    def append_shadow(self, variant_id: str, evidence: ShadowEvidence) -> None:
        self._append(variant_id, "shadow", asdict(evidence))

    def append_canary(self, variant_id: str, evidence: CanaryEvidence) -> None:
        self._append(variant_id, "canary", asdict(evidence))

    def _append(self, variant_id: str, phase: str, payload: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO deployment_evidence (
                    variant_id, phase, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    variant_id,
                    phase,
                    json.dumps(payload, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def latest_shadow(self, variant_id: str) -> ShadowEvidence | None:
        payload = self._latest(variant_id, "shadow")
        return ShadowEvidence(**payload) if payload is not None else None

    def latest_canary(self, variant_id: str) -> CanaryEvidence | None:
        payload = self._latest(variant_id, "canary")
        return CanaryEvidence(**payload) if payload is not None else None

    def _latest(self, variant_id: str, phase: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM deployment_evidence
                WHERE variant_id = ? AND phase = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (variant_id, phase),
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None
