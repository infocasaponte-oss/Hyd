# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from hydra.runtime.workspaces import WorkspaceManager


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            (Path(tmp) / "probe").symlink_to(tmp, target_is_directory=True)
        except OSError:
            return False
    return True


requires_symlinks = pytest.mark.skipif(
    not _can_symlink(), reason="creating symlinks requires privileges on this platform"
)


@requires_symlinks
def test_workspace_rejects_file_symlink(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (source / "leak.txt").symlink_to(outside)

    manager = WorkspaceManager(tmp_path / "workspaces", source_root=tmp_path)

    with pytest.raises(ValueError, match="symlink"):
        manager.create(uuid4(), source)


@requires_symlinks
def test_workspace_rejects_directory_symlink(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (source / "linked").symlink_to(outside, target_is_directory=True)

    manager = WorkspaceManager(tmp_path / "workspaces", source_root=tmp_path)

    with pytest.raises(ValueError, match="symlink"):
        manager.create(uuid4(), source)


def test_workspace_enforces_file_count_limit(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.py").write_text("a")
    (source / "b.py").write_text("b")

    manager = WorkspaceManager(tmp_path / "workspaces", source_root=tmp_path, max_files=1)

    with pytest.raises(ValueError, match="file count"):
        manager.create(uuid4(), source)


def test_workspace_enforces_byte_limit(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.bin").write_bytes(b"x" * 11)

    manager = WorkspaceManager(tmp_path / "workspaces", source_root=tmp_path, max_bytes=10)

    with pytest.raises(ValueError, match="byte size"):
        manager.create(uuid4(), source)


def test_workspace_copies_regular_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('ok')")

    manager = WorkspaceManager(tmp_path / "workspaces", source_root=tmp_path)
    workspace = manager.create(uuid4(), source)

    assert (workspace.root / "main.py").read_text() == "print('ok')"


def test_workspace_rejects_external_source_before_copy(tmp_path):
    allowed = tmp_path / "repos"
    allowed.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secret").write_text("private")
    manager = WorkspaceManager(tmp_path / "tasks", source_root=allowed)
    for source in (outside, "../private"):
        with pytest.raises(ValueError, match="outside"):
            manager.create(uuid4(), source)
    assert list((tmp_path / "tasks").iterdir()) == []


@requires_symlinks
def test_workspace_rejects_source_link_outside_root(tmp_path):
    allowed = tmp_path / "repos"
    allowed.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (allowed / "escape").symlink_to(outside, target_is_directory=True)
    manager = WorkspaceManager(tmp_path / "tasks", source_root=allowed)
    with pytest.raises(ValueError, match="outside"):
        manager.create(uuid4(), "escape")


@pytest.mark.parametrize('relative', ['org/repo', '.'])
def test_nested_repository_and_root_remain_compatible(tmp_path, relative):
    allowed = tmp_path / 'repositories'
    source = allowed / relative
    source.mkdir(parents=True)
    (source / 'main.py').write_text('original')
    manager = WorkspaceManager(tmp_path / 'tasks', source_root=allowed)
    workspace = manager.create(uuid4(), relative)
    assert (workspace.root / 'main.py').read_text() == 'original'


@requires_symlinks
def test_intermediate_link_inside_allowed_root_is_rejected(tmp_path):
    allowed = tmp_path / 'repositories'
    (allowed / 'real/repo').mkdir(parents=True)
    (allowed / 'alias').symlink_to(allowed / 'real', target_is_directory=True)
    manager = WorkspaceManager(tmp_path / 'tasks', source_root=allowed)
    with pytest.raises(ValueError, match='symlink'):
        manager.create(uuid4(), 'alias/repo')
