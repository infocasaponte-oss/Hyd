# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Output and argument helpers shared by the ``hydra`` CLI modules."""
from __future__ import annotations

import json


def print_json(obj) -> None:
    if hasattr(obj, "model_dump_json"):
        print(obj.model_dump_json(indent=2))
    else:
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def kv_pairs(pairs: list[str] | None) -> dict:
    """``key=value`` arguments; values are JSON when they parse, strings otherwise."""
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out
