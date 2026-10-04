# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Optimisation reports: candidates, frontier and selected variant."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from hydra.model_factory.physical.benchmark import BenchmarkResult
from hydra.core.runtime_paths import runtime_path


class OptimizationReport(BaseModel):
    hardware_name: str
    hardware_vram_mb: int
    measured: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    candidates: list[BenchmarkResult] = Field(default_factory=list)
    pareto_variant_ids: list[str] = Field(default_factory=list)
    selected_variant_id: str | None = None
    report_hash: str = ""


class OptimizationReportStore:
    def __init__(self, root: str | Path = runtime_path("optimization")):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, report: OptimizationReport) -> OptimizationReport:
        body = report.model_dump(mode="json", exclude={"report_hash"})
        report.report_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        path = self.root / f"{report.report_hash}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report
