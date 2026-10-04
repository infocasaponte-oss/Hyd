# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Content hashes of a task workspace."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

_SKIP_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "runtime"}


def workspace_sha256(root: str | Path) -> str:
    base = Path(root).resolve()
    digest = hashlib.sha256()

    paths: list[Path] = []
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_PARTS)
        for name in sorted(filenames):
            path = directory_path / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(base)
            if any(part in _SKIP_PARTS for part in relative.parts):
                continue
            paths.append(path)

    for path in sorted(paths, key=lambda item: str(item.relative_to(base))):
        relative = path.relative_to(base).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    return digest.hexdigest()
