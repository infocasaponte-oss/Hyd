# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4c): spans recorded around runtime steps live in ``hydra.observability.spans``
(``SpanRecorder``, kept here under its former name ``CognitiveTracer``)."""
from __future__ import annotations

from hydra.observability.spans import CognitiveSpan, TraceStore
from hydra.observability.spans import SpanRecorder as CognitiveTracer

__all__ = ["CognitiveSpan", "CognitiveTracer", "TraceStore"]
