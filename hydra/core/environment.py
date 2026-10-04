# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Shared early environment reader; process variables override the local .env."""
import os
from pathlib import Path

from dotenv import dotenv_values  # python-dotenv ships with pydantic-settings

_DOTENV = {k: v for k, v in dotenv_values(".env").items() if v is not None} if Path(".env").is_file() else {}


def _env(name: str, default: str | None = None) -> str | None:
    """Same precedence as Settings, for the few values read before Settings exists (runtime paths)."""
    value = os.environ.get(name)
    return value if value is not None else _DOTENV.get(name, default)


