# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Small vector helpers shared by the corpus deduplicator and the knowledge compiler."""
from __future__ import annotations

import math


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; 0.0 when either vector is zero."""
    num = sum(x * y for x, y in zip(a, b))
    da, db = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0
