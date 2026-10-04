# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.code_verification import (
    VerificationMode,
    VerificationPolicy,
    build_verification_report,
    extract_targeted_test,
)
from hydra.runtime.sandbox import SandboxResult


def test_extract_targeted_test_from_pytest_output(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "test_app.py").write_text("def test_x(): pass")
    assert extract_targeted_test("FAILED test_app.py:1 - boom", root) == "test_app.py"


def test_verification_requires_all_layers():
    failed = SandboxResult(False, "failed", 1)
    passed = SandboxResult(True, "passed", 0)
    report = build_verification_report(
        baseline=failed,
        targeted_target="test_app.py",
        targeted=passed,
        full_suite=passed,
        syntax=passed,
        ruff=passed,
        mypy=passed,
    )
    assert report.improvement_demonstrated is True
    assert report.verified is True

    rejected = build_verification_report(
        baseline=failed,
        targeted_target="test_app.py",
        targeted=passed,
        full_suite=passed,
        syntax=SandboxResult(False, "syntax", 1),
        ruff=passed,
        mypy=passed,
    )
    assert rejected.verified is False


def test_strict_policy_requires_mypy_and_ruff():
    failed = SandboxResult(False, "failed", 1)
    passed = SandboxResult(True, "passed", 0)
    report = build_verification_report(
        baseline=failed,
        targeted_target="test_app.py",
        targeted=passed,
        full_suite=passed,
        syntax=passed,
        ruff=passed,
        mypy=SandboxResult(False, "mypy failed", 1),
        policy=VerificationPolicy(VerificationMode.STRICT),
    )
    assert report.verified is False
    assert report.analysis_mode == VerificationMode.STRICT


def test_advisory_policy_records_static_failure_without_blocking():
    failed = SandboxResult(False, "failed", 1)
    passed = SandboxResult(True, "passed", 0)
    report = build_verification_report(
        baseline=failed,
        targeted_target="test_app.py",
        targeted=passed,
        full_suite=passed,
        syntax=passed,
        ruff=SandboxResult(False, "ruff failed", 1),
        mypy=SandboxResult(False, "mypy failed", 1),
    )
    assert report.verified is True
    assert report.ruff_passed is False
    assert report.mypy_passed is False


def test_ruff_required_blocks_ruff_but_not_mypy_failure():
    failed = SandboxResult(False, "failed", 1)
    passed = SandboxResult(True, "passed", 0)
    report = build_verification_report(
        baseline=failed,
        targeted_target="test_app.py",
        targeted=passed,
        full_suite=passed,
        syntax=passed,
        ruff=SandboxResult(False, "ruff failed", 1),
        mypy=passed,
        policy=VerificationPolicy(VerificationMode.RUFF_REQUIRED),
    )
    assert report.verified is False

    mypy_only_failure = build_verification_report(
        baseline=failed,
        targeted_target="test_app.py",
        targeted=passed,
        full_suite=passed,
        syntax=passed,
        ruff=passed,
        mypy=SandboxResult(False, "mypy failed", 1),
        policy=VerificationPolicy(VerificationMode.RUFF_REQUIRED),
    )
    assert mypy_only_failure.verified is True
