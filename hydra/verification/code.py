# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Verification of a code change: baseline vs targeted vs full test runs plus syntax, ruff and mypy,
under a verification mode (advisory, ruff-required, strict)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from hydra.tools.oci_sandbox import SandboxResult


class VerificationMode(StrEnum):
    ADVISORY = "advisory"
    RUFF_REQUIRED = "ruff-required"
    STRICT = "strict"


@dataclass(frozen=True)
class VerificationPolicy:
    mode: VerificationMode = VerificationMode.ADVISORY


@dataclass(frozen=True)
class VerificationReport:
    baseline_failed: bool
    targeted_target: str | None
    targeted_passed: bool
    full_suite_passed: bool
    syntax_passed: bool
    ruff_passed: bool
    mypy_passed: bool
    analysis_mode: VerificationMode
    improvement_demonstrated: bool
    verified: bool


def extract_targeted_test(pytest_output: str, workspace: str | Path) -> str | None:
    root = Path(workspace).resolve()
    for token in pytest_output.split():
        cleaned = token.strip("()[]{}<>,;'\"")
        marker = cleaned.find(".py")
        if marker < 0:
            continue
        raw = cleaned[: marker + 3]
        candidate = (root / raw).resolve()
        if candidate == root or root not in candidate.parents:
            continue
        if candidate.is_file():
            return str(candidate.relative_to(root))
    return None


def build_verification_report(
    *,
    baseline: SandboxResult,
    targeted_target: str | None,
    targeted: SandboxResult,
    full_suite: SandboxResult,
    syntax: SandboxResult,
    ruff: SandboxResult,
    mypy: SandboxResult,
    policy: VerificationPolicy | None = None,
) -> VerificationReport:
    policy = policy or VerificationPolicy()
    improvement = (not baseline.ok) and full_suite.ok
    static_gate = True
    if policy.mode in {VerificationMode.RUFF_REQUIRED, VerificationMode.STRICT}:
        static_gate = static_gate and ruff.ok
    if policy.mode == VerificationMode.STRICT:
        static_gate = static_gate and mypy.ok
    verified = (
        improvement
        and targeted.ok
        and full_suite.ok
        and syntax.ok
        and static_gate
    )
    return VerificationReport(
        baseline_failed=not baseline.ok,
        targeted_target=targeted_target,
        targeted_passed=targeted.ok,
        full_suite_passed=full_suite.ok,
        syntax_passed=syntax.ok,
        ruff_passed=ruff.ok,
        mypy_passed=mypy.ok,
        analysis_mode=policy.mode,
        improvement_demonstrated=improvement,
        verified=verified,
    )


def changed_python_paths(diff: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("+++ "):
            continue
        raw = line[4:].split("\t", 1)[0].strip()
        if raw == "/dev/null":
            continue
        raw = raw.removeprefix("b/")
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts:
            continue
        normalized = path.as_posix()
        if normalized.endswith(".py") and normalized not in seen:
            paths.append(normalized)
            seen.add(normalized)
    return paths
