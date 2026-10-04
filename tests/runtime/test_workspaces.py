# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.workspaces import WorkspaceManager


def test_task_workspace_is_copy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("original")
    manager = WorkspaceManager(tmp_path / "runtime", source_root=tmp_path)
    workspace = manager.create(uuid4(), source)
    (workspace.root / "file.txt").write_text("changed")
    assert (source / "file.txt").read_text() == "original"
    manager.destroy(workspace)
    assert not workspace.root.exists()
