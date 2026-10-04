# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F4c: runtime spans in the platform (``hydra.observability.spans``) with an optional OTLP destination."""
from __future__ import annotations

import time
from uuid import uuid4

import pytest

from hydra.observability.spans import OtlpSpanExporter, SpanRecorder, TraceStore, otlp_span
from hydra.runtime.observability import CognitiveSpan, CognitiveTracer


def test_runtime_names_are_the_platform_recorder():
    assert CognitiveTracer is SpanRecorder and CognitiveSpan.__module__ == "hydra.observability.spans"


def test_recorder_keeps_its_behaviour(tmp_path):
    recorder = SpanRecorder(TraceStore(tmp_path / "traces.jsonl"))
    with recorder.span("routing", trace_id="t1", attributes={"capability": "code"}) as span:
        assert span.status == "in_progress"
    with pytest.raises(ValueError), recorder.span("inference", trace_id="t1"):
        raise ValueError("bad")
    first, second = recorder.store.recent()
    assert (first["name"], first["status"], first["attributes"]) == ("routing", "ok", {"capability": "code"})
    assert (second["status"], second["error_type"]) == ("error", "ValueError")
    assert first["duration_ms"] is not None and first["duration_ms"] >= 0


def test_spans_are_exported_as_otlp(tmp_path, monkeypatch):
    posted = []
    monkeypatch.setattr(OtlpSpanExporter, "_post", lambda self, spans: posted.extend(spans))
    task = uuid4()
    recorder = SpanRecorder(TraceStore(tmp_path / "t.jsonl"), OtlpSpanExporter("http://collector:4318/"))
    with recorder.span("verification", trace_id=str(task), task_id=task, attributes={"accepted": True}):
        pass
    deadline = time.monotonic() + 5
    while not posted and time.monotonic() < deadline:
        time.sleep(0.01)
    [span] = posted
    assert span["traceId"] == str(task).replace("-", "") and len(span["spanId"]) == 16
    assert span["name"] == "verification" and span["status"] == {"code": 1}
    assert {"key": "hydra.accepted", "value": {"boolValue": True}} in span["attributes"]
    assert int(span["endTimeUnixNano"]) >= int(span["startTimeUnixNano"])


def test_non_hex_trace_ids_are_hashed_stably():
    a = otlp_span(CognitiveSpan(trace_id="trace-alpha", name="x", duration_ms=1.0))
    b = otlp_span(CognitiveSpan(trace_id="trace-alpha", name="y", duration_ms=1.0))
    assert a["traceId"] == b["traceId"] and len(a["traceId"]) == 32 and int(a["traceId"], 16) >= 0


def test_a_stuck_collector_never_blocks_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(OtlpSpanExporter, "_post", lambda self, spans: time.sleep(60))
    exporter = OtlpSpanExporter("http://collector:4318", max_queue=3)
    recorder = SpanRecorder(TraceStore(tmp_path / "t.jsonl"), exporter)
    started = time.monotonic()
    for i in range(20):
        with recorder.span(f"s{i}", trace_id="t"):
            pass
    assert time.monotonic() - started < 2 and exporter.dropped > 0
    assert len(recorder.store.recent()) == 20  # the store always gets every span
