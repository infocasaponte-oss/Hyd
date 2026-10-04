# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.workspace_hash import workspace_sha256


def test_workspace_hash_changes_with_content(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "app.py"
    path.write_text("VALUE = 1\n")
    before = workspace_sha256(root)
    path.write_text("VALUE = 2\n")
    after = workspace_sha256(root)
    assert before != after


def test_workspace_hash_ignores_git_metadata(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n")
    git = root / ".git"
    git.mkdir()
    marker = git / "HEAD"
    marker.write_text("one")
    first = workspace_sha256(root)
    marker.write_text("two")
    second = workspace_sha256(root)
    assert first == second
