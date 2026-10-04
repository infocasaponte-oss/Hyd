# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Crash-safe replacement of small state files (JSON stores, manifests, ACLs).

``Path.write_text`` truncates first and writes second: a crash or a concurrent writer leaves a
half-written JSON that the next start cannot parse. Here the content goes to a unique temporary
file in the same directory, is fsynced and then atomically renamed over the target. Windows
readers holding the target open can make the rename fail transiently, so it is retried briefly."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def write_bytes_atomic(path: str | Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.025 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_text_atomic(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    write_bytes_atomic(path, text.encode(encoding))
