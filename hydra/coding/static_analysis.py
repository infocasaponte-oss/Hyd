# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Static-analysis verdicts (ruff, mypy) on a change."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from hydra.tools.oci_sandbox import SandboxResult


class AnalysisKind(StrEnum):
    RUFF = "ruff"
    MYPY = "mypy"


@dataclass(frozen=True)
class AnalysisResult:
    kind: AnalysisKind
    ok: bool
    exit_code: int
    output: str
    targets: tuple[str, ...]


def from_sandbox(
    kind: AnalysisKind,
    result: SandboxResult,
    targets: list[str],
) -> AnalysisResult:
    return AnalysisResult(
        kind=kind,
        ok=result.ok,
        exit_code=result.exit_code,
        output=result.output,
        targets=tuple(targets),
    )
