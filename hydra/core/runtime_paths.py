# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Where the HYDRA-SO runtime line keeps its local state.

``HYDRA_RUNTIME_DIR`` (default ``runtime``, relative to the working directory as before) roots
every runtime store: event and provenance chains, SQLite outbox/metrics, artifacts, replays,
workspaces. Store defaults are resolved when their module is imported, so the variable must be
set before the runtime line is loaded (environment, ``.env`` or test configuration)."""

from __future__ import annotations

from pathlib import Path

from hydra.core.environment import _env

RUNTIME_DIR = Path(_env("HYDRA_RUNTIME_DIR", "runtime"))


def runtime_path(*parts: str) -> str:
    return str(RUNTIME_DIR.joinpath(*parts))
