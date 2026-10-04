# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.code_agent import extract_unified_diff
from hydra.runtime.coding_request import resolve_repository


def test_extracts_fenced_unified_diff():
    text = "~~~diff\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n~~~"
    text = text.replace("~~~", chr(96) * 3)
    diff = extract_unified_diff(text)
    assert diff.startswith("--- a/a.py")
    assert diff.endswith("\n")


def test_rejects_non_diff_output():
    with pytest.raises(ValueError):
        extract_unified_diff("I think you should change the function.")


def test_repository_escape_rejected(tmp_path):
    root = tmp_path / "repos"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_repository(root, "../outside")
