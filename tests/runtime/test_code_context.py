# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.code_context import CodeContextSelector


def test_selector_prefers_traceback_python_file(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("def broken():\n    return 1\n")
    (root / "other.py").write_text("VALUE = 2\n")

    selected = CodeContextSelector().select(
        root,
        "FAILED app.py:12 - AssertionError",
    )

    assert [item.path for item in selected] == ["app.py"]
    assert "def broken" in selected[0].text


def test_selector_rejects_path_escape(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 'nope'")

    selected = CodeContextSelector().select(root, "../outside.py:1")

    assert all("outside.py" != item.path for item in selected)


def test_selector_respects_total_char_budget(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("a" * 100)
    (root / "b.py").write_text("b" * 100)

    selected = CodeContextSelector(max_chars=50).select(root, "")

    assert sum(len(item.text) for item in selected) <= 50
