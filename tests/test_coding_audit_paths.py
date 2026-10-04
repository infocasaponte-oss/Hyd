# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F4k-1: repository resolution and replay manifest paths stay confined (same behaviour as before the move)."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from hydra.audit.replay import ReplayManifest, ReplayStore
from hydra.coding.request import resolve_repository


def test_repositories_resolve_inside_the_root_only(tmp_path):
    root = tmp_path / "repos"
    (root / "org" / "repo").mkdir(parents=True)
    (tmp_path / "private").mkdir()
    assert resolve_repository(root, "org/repo") == (root / "org" / "repo").resolve()
    assert resolve_repository(root, ".") == root.resolve()
    for escape in ("../private", "org/../../private", str(tmp_path / "private")):
        with pytest.raises(ValueError, match="escape"):
            resolve_repository(root, escape)
    with pytest.raises(ValueError, match="does not exist"):
        resolve_repository(root, "missing")


def test_sibling_with_same_prefix_is_rejected(tmp_path):
    root = tmp_path / "repos"
    sibling = tmp_path / "repos-private"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(ValueError, match="escape"):
        resolve_repository(root, "../repos-private")


def test_root_must_exist_and_be_a_directory(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="does not exist"):
        resolve_repository(missing, ".")
    file = tmp_path / "file"
    file.write_text("content")
    with pytest.raises(ValueError, match="does not exist"):
        resolve_repository(file, ".")


@pytest.mark.skipif(os.name == "nt", reason="POSIX filesystem root")
def test_filesystem_root_supports_nested_repository(tmp_path):
    assert resolve_repository("/", str(tmp_path)) == tmp_path.resolve()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_link_to_nested_directory_inside_root_is_accepted(tmp_path):
    root = tmp_path / "repos"
    nested = root / "org" / "repo"
    nested.mkdir(parents=True)
    (root / "alias").symlink_to(nested, target_is_directory=True)
    assert resolve_repository(root, "alias") == nested.resolve()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_link_out_of_the_root_is_rejected(tmp_path):
    root = tmp_path / "repos"
    root.mkdir()
    (tmp_path / "private").mkdir()
    (root / "escape").symlink_to(tmp_path / "private", target_is_directory=True)
    with pytest.raises(ValueError, match="escape"):
        resolve_repository(root, "escape")


def test_replay_manifests_are_named_by_task_uuid(tmp_path):
    store = ReplayStore(tmp_path / "replay")
    task = uuid4()
    store.put(ReplayManifest(task_id=task, trace_id="t", hydra_version="1"))
    assert (tmp_path / "replay" / f"{task}.json").is_file()
    assert store.get(task).trace_id == "t" and store.get(uuid4()) is None
    with pytest.raises(ValueError):
        store.get("../../etc/passwd")
