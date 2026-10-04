# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

_PROCESS_LOCKS: dict[str, Lock] = {}
_PROCESS_LOCKS_GUARD = Lock()


def lock_for(path: str | Path) -> Lock:
    key = str(Path(path).resolve())
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, Lock())


def canonical_hash(body: dict[str, Any]) -> str:
    raw = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(raw).hexdigest()
