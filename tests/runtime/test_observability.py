# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from uuid import uuid4

import pytest

from hydra.runtime.observability import CognitiveTracer, TraceStore


def test_cognitive_span_records_duration_without_payloads(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = CognitiveTracer(TraceStore(path))
    with tracer.span(
        "routing",
        trace_id="trace",
        task_id=uuid4(),
        attributes={"capability": "reasoning.general"},
    ):
        pass

    raw = json.loads(path.read_text())
    assert raw["status"] == "ok"
    assert raw["duration_ms"] >= 0
    assert raw["attributes"]["capability"] == "reasoning.general"


def test_cognitive_span_records_error_type(tmp_path):
    path = tmp_path / "traces.jsonl"
    tracer = CognitiveTracer(TraceStore(path))

    with pytest.raises(ValueError), tracer.span("execution", trace_id="trace"):
        raise ValueError("secret detail")

    raw = json.loads(path.read_text())
    assert raw["status"] == "error"
    assert raw["error_type"] == "ValueError"
    assert "secret detail" not in path.read_text()
