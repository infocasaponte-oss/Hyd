# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Per-request evidence of live traffic, and the promotion evidence measured from it.

Every routed request appends one JSONL record: which variants served it (primary, shadow copy,
canary), whether each call failed, how long it took and whether shadow and primary agreed. The
deployment controller derives ``ShadowEvidence`` / ``CanaryEvidence`` from these records instead
of trusting numbers sent by an operator.

The records live in a ``hydra.core.eventlog`` log: ``runtime-evidence.jsonl`` under the runtime
directory, or the PostgreSQL stream ``runtime/evidence.jsonl`` that every node writes to, so a
promotion is judged on the traffic of the whole cluster. Phases are delimited by log sequence
numbers (``position``)."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import threading
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hydra.core.eventlog import FileLog
from hydra.deploy.deployment_evidence import CanaryEvidence, ShadowEvidence
from hydra.core.runtime_paths import runtime_path


@dataclass(frozen=True)
class RuntimeEvidence:
    trace_id: str
    capability: str
    primary_variant_id: str
    shadow_variant_id: str | None
    primary_output_sha256: str
    shadow_output_sha256: str | None
    exact_agreement: bool | None
    created_at: str
    primary_latency_ms: float | None = None
    shadow_error: bool | None = None
    shadow_latency_ms: float | None = None
    canary_variant_id: str | None = None
    canary_error: bool | None = None
    canary_latency_ms: float | None = None
    primary_error: bool | None = None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def p95(values: list[float], presorted: bool = False) -> float:
    """Nearest-rank 95th percentile (0.0 for no values: the request count gate fails first)."""
    if not values:
        return 0.0
    ordered = values if presorted else sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


class RuntimeEvidenceStore:
    STREAM = "runtime/evidence.jsonl"

    def __init__(self, path: str | Path = runtime_path("runtime-evidence.jsonl"), log=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log if log is not None else FileLog(self.path, self.STREAM)
        self._lock = threading.Lock()
        self._tallies: dict[tuple[str, str, int], _Tally] = {}

    def append(
        self,
        *,
        trace_id: str,
        capability: str,
        primary_variant_id: str,
        primary_output: str,
        shadow_variant_id: str | None = None,
        shadow_output: str | None = None,
        primary_latency_ms: float | None = None,
        shadow_error: bool | None = None,
        shadow_latency_ms: float | None = None,
        canary_variant_id: str | None = None,
        canary_error: bool | None = None,
        canary_latency_ms: float | None = None,
        primary_error: bool | None = None,
    ) -> RuntimeEvidence:
        if shadow_variant_id is not None and shadow_error is None:
            shadow_error = shadow_output is None
        record = RuntimeEvidence(
            trace_id=trace_id,
            capability=capability,
            primary_variant_id=primary_variant_id,
            shadow_variant_id=shadow_variant_id,
            primary_output_sha256=_sha256(primary_output),
            shadow_output_sha256=_sha256(shadow_output) if shadow_output is not None else None,
            exact_agreement=primary_output == shadow_output if shadow_output is not None else None,
            created_at=datetime.now(UTC).isoformat(),
            primary_latency_ms=primary_latency_ms,
            shadow_error=shadow_error,
            shadow_latency_ms=shadow_latency_ms,
            canary_variant_id=canary_variant_id,
            canary_error=canary_error,
            canary_latency_ms=canary_latency_ms,
            primary_error=primary_error,
        )
        self.log.append(json.dumps(asdict(record), sort_keys=True))
        return record

    def position(self) -> int:
        """Sequence number of the last evidence record. A phase records it when it starts and only
        counts the records written after it: exact, unlike timestamps that can tie at the transition."""
        return len(self.log)

    def records(self, start: int = 0) -> Iterator[dict]:
        for record, _ in self._complete_records(start):
            yield record

    def _complete_records(self, start: int) -> Iterator[tuple[dict, int]]:
        """Records after sequence ``start`` with their sequence number. A line still being written is
        not an entry yet (``FileLog``); a corrupt one is skipped."""
        for seq, line in self.log.read(start):
            try:
                yield json.loads(line), seq
            except ValueError:
                continue  # a corrupt line is not evidence

    def seq_at_byte_offset(self, offset: int) -> int | None:
        """Translate a phase start recorded as a byte offset in ``runtime-evidence.jsonl`` (before the
        evidence moved to sequence numbers) into the number of records before it. None when that file
        is gone: the caller must not guess."""
        if not self.path.is_file():
            return None
        seq = 0
        with self.path.open("rb") as handle:
            consumed = 0
            for raw in handle:
                if not raw.endswith(b"\n") or consumed + len(raw) > offset:
                    break
                consumed += len(raw)
                if raw.strip():
                    seq += 1
        return seq

    def _advance(self, kind: str, variant_id: str, start: int) -> _Tally:
        """Incremental aggregate for one phase: only the records written since the previous query are
        read, so polling a long SHADOW/CANARY phase stays cheap."""
        with self._lock:
            key = (kind, variant_id, start)
            tally = self._tallies.get(key)
            if tally is None or self.position() < tally.offset:  # first query, or the log was replaced
                tally = self._tallies[key] = _Tally(offset=start)
            for record, offset in self._complete_records(tally.offset):
                tally.offset = offset
                (_fold_shadow if kind == "shadow" else _fold_canary)(tally, record, variant_id)
            return tally

    def shadow_evidence(self, variant_id: str, start: int = 0) -> ShadowEvidence:
        """Measured shadow behaviour of ``variant_id``: every mirrored request is a sample, a failed
        shadow call is an error, agreement is over the shadow calls that answered."""
        t = self._advance("shadow", variant_id, start)
        answered = t.samples - t.errors
        return ShadowEvidence(
            samples=t.samples,
            agreement_rate=t.agreed / answered if answered else 0.0,
            error_rate=t.errors / t.samples if t.samples else 0.0,
        )

    def canary_evidence(self, variant_id: str, start: int = 0) -> CanaryEvidence:
        """Measured canary behaviour of ``variant_id``: requests routed to it, the share that failed
        (including those whose fallback failed too) and the p95 latency of those it answered."""
        t = self._advance("canary", variant_id, start)
        return CanaryEvidence(
            requests=t.samples,
            error_rate=t.errors / t.samples if t.samples else 0.0,
            p95_latency_ms=p95(t.latencies, presorted=True),
        )


@dataclass
class _Tally:
    offset: int
    samples: int = 0
    errors: int = 0
    agreed: int = 0
    latencies: list[float] = field(default_factory=list)  # kept sorted


def _fold_shadow(t: _Tally, record: dict, variant_id: str) -> None:
    if record.get("shadow_variant_id") != variant_id:
        return
    t.samples += 1
    failed = record.get("shadow_error")
    if failed is None:  # records written before errors were tracked
        failed = record.get("shadow_output_sha256") is None
    if failed:
        t.errors += 1
    elif record.get("exact_agreement"):
        t.agreed += 1


def _fold_canary(t: _Tally, record: dict, variant_id: str) -> None:
    if record.get("canary_variant_id") != variant_id:
        return
    t.samples += 1
    if record.get("canary_error"):
        t.errors += 1
    elif record.get("canary_latency_ms") is not None:
        bisect.insort(t.latencies, float(record["canary_latency_ms"]))
