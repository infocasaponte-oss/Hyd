# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.sandbox import SandboxResult
from hydra.runtime.static_analysis import AnalysisKind, from_sandbox


def test_static_analysis_wraps_sandbox_result():
    result = from_sandbox(
        AnalysisKind.RUFF,
        SandboxResult(True, "ok", 0),
        ["app.py"],
    )
    assert result.ok is True
    assert result.kind == AnalysisKind.RUFF
    assert result.targets == ("app.py",)
