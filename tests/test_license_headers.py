# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Every tracked text file carries the proprietary copyright notice (JSON and JSON Lines cannot hold comments; pinned patches must stay byte-exact)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OWNER = "Luis Manuel Cousido Hermida"
BINARY_OR_COMMENTLESS = {".json", ".jsonl", ".patch", ".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".gguf", ".safetensors", ".pyc"}


def _tracked() -> list[Path]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if line]


def test_every_tracked_text_file_has_the_copyright_notice():
    missing = [str(p.relative_to(ROOT)) for p in _tracked()
               if p.suffix.lower() not in BINARY_OR_COMMENTLESS and p.is_file()
               and OWNER not in p.read_text(encoding="utf-8", errors="replace")]
    assert not missing, f"missing copyright notice: {missing}"
