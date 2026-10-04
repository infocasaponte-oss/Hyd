# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.patching import PatchTool
from hydra.runtime.tools import Workspace


def test_patch_rejects_parent_escape(tmp_path):
    patcher = PatchTool(Workspace(tmp_path))
    diff = "--- a/../escape.txt\n+++ b/../escape.txt\n@@ -0,0 +1 @@\n+x\n"
    with pytest.raises(ValueError):
        patcher.apply(diff)


def test_patch_applies_inside_git_workspace(tmp_path):
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("old\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    diff = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    result = PatchTool(Workspace(tmp_path)).apply(diff)
    assert result.ok
    assert (tmp_path / "a.txt").read_text() == "new\n"


def test_patch_rejects_symlink_mode(tmp_path):
    patcher = PatchTool(Workspace(tmp_path))
    diff = (
        "diff --git a/link b/link\n"
        "new file mode 120000\n"
        "--- /dev/null\n"
        "+++ b/link\n"
        "@@ -0,0 +1 @@\n"
        "+../outside\n"
    )
    with pytest.raises(ValueError, match="Symlink"):
        patcher.apply(diff)


def test_patch_rejects_rename_metadata(tmp_path):
    patcher = PatchTool(Workspace(tmp_path))
    diff = (
        "diff --git a/a.txt b/b.txt\n"
        "rename from a.txt\n"
        "rename to b.txt\n"
        "--- a/a.txt\n"
        "+++ b/b.txt\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    with pytest.raises(ValueError, match="Unsupported patch metadata"):
        patcher.apply(diff)


def test_patch_rejects_git_metadata_path(tmp_path):
    patcher = PatchTool(Workspace(tmp_path))
    diff = (
        "--- a/.git/config\n"
        "+++ b/.git/config\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    with pytest.raises(ValueError, match="Git metadata"):
        patcher.apply(diff)


def test_failed_patch_restores_existing_file(tmp_path):
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("old\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    diff = (
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1 +1 @@\n"
        "-not-the-current-content\n"
        "+new\n"
    )

    result = PatchTool(Workspace(tmp_path)).apply(diff)

    assert not result.ok
    assert (tmp_path / "a.txt").read_text() == "old\n"


def test_reverse_restores_applied_patch(tmp_path):
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("old\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    diff = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
    patcher = PatchTool(Workspace(tmp_path))

    assert patcher.apply(diff).ok
    assert (tmp_path / "a.txt").read_text() == "new\n"
    assert patcher.reverse(diff).ok
    assert (tmp_path / "a.txt").read_text() == "old\n"
