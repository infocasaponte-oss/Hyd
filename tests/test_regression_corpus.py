# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.training.evaluate_corpus import verification_program
from hydra.training.regression_corpus import build
from hydra.tools.sandbox import SubprocessSandbox


def test_regression_is_frozen_and_not_training_data(tmp_path):
    manifest = build(tmp_path)
    assert build(tmp_path) == manifest
    rows = [json.loads(line) for line in (tmp_path / "test.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 12 and len({row["family"] for row in rows}) == 12
    assert all(row["training_allowed"] is False for row in rows)
    (tmp_path / "test.jsonl").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        build(tmp_path)


@pytest.mark.parametrize("code,expected", [
    ("def solve(x): return x+1", True),
    ("raise SystemExit(0)", False),
    ("def solve(x): return x", False),
])
async def test_verification_requires_assertion_completion(code, expected):
    # Only fixed trusted programs execute in this development sandbox.
    program, marker = verification_program(code, [{"input": 1, "expected": 2}])
    result = await SubprocessSandbox().execute_python(program)
    assert (result.exit_code == 0 and marker in result.stdout.splitlines()) is expected
