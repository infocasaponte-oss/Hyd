# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Cognitive spans recorded around the steps of a runtime-line task (routing, planning, inference,
verification...), with two destinations:

* a ``TraceStore`` (``traces.jsonl``, or ``hydra.core.native_stores.PostgresTraceStore`` shared by the
  cluster), read by the operating metrics;
* optionally an OTLP/HTTP collector (``HYDRA_OTEL_ENDPOINT``), the same one the platform's event-driven
  ``hydra.observability.tracing.CognitiveTracer`` exports to. Spans are queued and sent by a background
  thread: exporting never blocks or fails a request.

``SpanRecorder`` is what the runtime line called ``CognitiveTracer`` (``hydra.runtime.observability``
re-exports it under that name); it is a context manager around a step, not a bus subscriber."""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from hydra.core.runtime_paths import runtime_path

log = logging.getLogger("hydra.tracing")


@dataclass
class CognitiveSpan:
    span_id: UUID = field(default_factory=uuid4)
    trace_id: str = ""
    task_id: UUID | None = None
    name: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_ms: float | None = None
    status: str = "in_progress"
    error_type: str | None = None
    attributes: dict = field(default_factory=dict)


class TraceStore:
    def __init__(self, path: str | Path = runtime_path("traces.jsonl")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, span: CognitiveSpan) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(span), sort_keys=True, default=str) + "\n")

    def recent(self, limit: int = 10_000) -> list[dict]:
        """The last ``limit`` spans (operating metrics). On PostgreSQL
        (``hydra.core.native_stores.PostgresTraceStore``) they are the spans of the whole cluster."""
        if not self.path.exists():
            return []
        lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        return [json.loads(line) for line in lines[-limit:]]


def _hex_id(value: str, size: int) -> str:
    """OTLP ids are hex: keep a hex id as is, hash anything else (stable per value)."""
    raw = value.replace("-", "").lower()
    if len(raw) >= size and all(c in "0123456789abcdef" for c in raw[:size]):
        return raw[:size]
    return hashlib.sha256(value.encode()).hexdigest()[:size]


def otlp_span(span: CognitiveSpan) -> dict:
    start = datetime.fromisoformat(span.started_at).timestamp()
    end = start + (span.duration_ms or 0.0) / 1000
    attrs = {"hydra.task_id": str(span.task_id) if span.task_id else None, "hydra.error_type": span.error_type,
             **{f"hydra.{k}": v for k, v in span.attributes.items()}}

    def value(v):
        if isinstance(v, bool):
            return {"boolValue": v}
        if isinstance(v, int):
            return {"intValue": str(v)}
        if isinstance(v, float):
            return {"doubleValue": v}
        return {"stringValue": str(v)}

    return {"traceId": _hex_id(span.trace_id or str(span.span_id), 32), "spanId": _hex_id(str(span.span_id), 16),
            "name": span.name, "kind": 1, "startTimeUnixNano": str(int(start * 1e9)),
            "endTimeUnixNano": str(int(end * 1e9)),
            "attributes": [{"key": k, "value": value(v)} for k, v in attrs.items() if v is not None],
            "status": {"code": 2 if span.status == "error" else 1}}


class OtlpSpanExporter:
    """Background batches to ``<endpoint>/v1/traces``. Bounded: when the collector is slow or down, the
    newest spans are dropped (counted in ``dropped``) instead of growing memory."""

    def __init__(self, endpoint: str, service: str = "hydra", batch: int = 64, max_queue: int = 10_000) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.service = service
        self.batch = batch
        self.dropped = 0
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._run, name="hydra-otlp-spans", daemon=True)
        self._thread.start()

    def submit(self, span: CognitiveSpan) -> None:
        try:
            self._queue.put_nowait(otlp_span(span))
        except queue.Full:
            self.dropped += 1

    def _post(self, spans: list[dict]) -> None:
        import httpx

        body = {"resourceSpans": [{"resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": self.service}}]},
            "scopeSpans": [{"scope": {"name": "hydra.runtime"}, "spans": spans}]}]}
        try:
            httpx.post(f"{self.endpoint}/v1/traces", json=body, timeout=5)
        except Exception:  # noqa: BLE001 - observability must never break the request path
            log.debug("OTLP span export failed", exc_info=True)

    def _run(self) -> None:
        while True:
            spans = [self._queue.get()]
            while len(spans) < self.batch:
                try:
                    spans.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._post(spans)


class SpanRecorder:
    """Context manager around a task step: records the span in ``store`` and, with ``exporter``, sends it
    to the OTLP collector too."""

    def __init__(self, store: TraceStore | None = None, exporter: OtlpSpanExporter | None = None):
        self.store = store or TraceStore()
        self.exporter = exporter

    @contextmanager
    def span(
        self,
        name: str,
        *,
        trace_id: str,
        task_id: UUID | None = None,
        attributes: dict | None = None,
    ) -> Iterator[CognitiveSpan]:
        span = CognitiveSpan(
            trace_id=trace_id,
            task_id=task_id,
            name=name,
            attributes=attributes or {},
        )
        started = perf_counter()
        try:
            yield span
        except Exception as exc:
            span.status = "error"
            span.error_type = type(exc).__name__
            raise
        else:
            span.status = "ok"
        finally:
            span.duration_ms = (perf_counter() - started) * 1000
            self.store.append(span)
            if self.exporter is not None:
                self.exporter.submit(span)
