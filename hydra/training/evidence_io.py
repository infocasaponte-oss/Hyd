# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Atomic local evidence writes (unique temporary file, fsync, bounded retries on Windows locks)."""
import json
from pathlib import Path

from hydra.core.atomic import write_text_atomic


def write_json(path: Path, data: dict):
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))
