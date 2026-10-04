# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import tempfile
from pathlib import Path

import pytest

from hydra.tools.workspace import WorkspaceManager, scan_source


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            (Path(tmp) / "probe").symlink_to(tmp, target_is_directory=True)
        except OSError:
            return False
    return True


@pytest.mark.parametrize("task_id", ["../escape", "a/b", "", "..", "/abs"])
def test_task_id_cannot_escape_workspace_root(tmp_path, task_id):
    manager = WorkspaceManager(tmp_path / "ws")
    with pytest.raises(ValueError, match="invalid task id"):
        manager.create(task_id, files={"a.py": "x = 1\n"})
    assert manager.get(task_id) is None


@pytest.mark.parametrize("rel", ["../../outside.py", "../escape.txt"])
def test_inline_files_cannot_escape_workspace(tmp_path, rel):
    manager = WorkspaceManager(tmp_path / "ws")
    with pytest.raises(ValueError, match="escapes workspace"):
        manager.create("t1", files={rel: "leak"})
    assert not (tmp_path / "outside.py").exists()


def test_scan_enforces_file_count(tmp_path):
    for index in range(4):
        (tmp_path / f"f{index}.txt").write_text("x")
    with pytest.raises(ValueError, match="file count"):
        scan_source(tmp_path, max_files=3)


def test_blocked_directories_are_not_counted(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "big").write_bytes(b"x" * 1024)
    (tmp_path / "main.py").write_bytes(b"print(1)\n")
    assert scan_source(tmp_path, max_bytes=100) == (1, 9)


@pytest.mark.skipif(not _can_symlink(), reason="creating symlinks requires privileges on this platform")
def test_source_with_symlink_to_outside_is_rejected(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("token")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "leak.txt").symlink_to(secret)
    manager = WorkspaceManager(tmp_path / "ws")
    with pytest.raises(ValueError, match="symlink"):
        manager.create("t2", source=repo)
