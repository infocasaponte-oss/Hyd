# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Confine client-supplied paths to an allowed root.

API clients must never name arbitrary host paths: they may only refer to directories below
a configured root (``HYDRA_REPOSITORIES_ROOT``). Symlinks are resolved before the check, so a
link inside the root cannot point outside it."""

from __future__ import annotations

import os
import re
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PathNotAllowed(ValueError):
    """The path resolves outside its allowed root."""


def confine(root: str | Path, user_path: str) -> Path:
    """Resolve ``user_path`` (relative to ``root``) and require it to stay inside ``root``."""
    base = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(base, user_path))
    if candidate != base and not candidate.startswith(base + os.sep):
        raise PathNotAllowed(f"path is outside the allowed root: {user_path}")
    return Path(candidate)


def safe_id(value: str, what: str = "identifier") -> str:
    """An identifier that is also used as a single path component (no separators, no '..')."""
    if not _SAFE_ID.match(value) or ".." in value:
        raise PathNotAllowed(f"invalid {what}: {value!r}")
    return value
