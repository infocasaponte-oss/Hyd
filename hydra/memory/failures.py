# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Failure Memory: operational errors, kept apart from knowledge memory.

    model X fails with structured output      model Y breaks with context > 80k
    tool Z usually times out                  runtime R runs out of memory

The scheduler consults it to avoid known failure patterns before they happen.

Persisted as the ``failure_memory.json`` document (``hydra.core.docstore``). Every node counts its
own observations and adds them to the stored totals when it saves (it never overwrites what other
nodes recorded), then adopts the merged totals; between saves it also picks up the totals other
nodes stored.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from hydra.core.events import EventType, HydraEvent

CONDITION_KEYS = ("ctx_bucket", "structured", "tools", "images")


class FailurePattern(BaseModel):
    subject_type: str  # model | tool
    subject_id: str
    kind: str
    condition: dict = Field(default_factory=dict)
    failures: int = 0
    last_seen: datetime | None = None


def _cond(payload: dict) -> tuple:
    return tuple((k, payload.get(k)) for k in CONDITION_KEYS if k in payload)


class FailureMemory:
    def __init__(self, path: Path | None = None, min_observations: int = 3, avoid_above: float = 0.5,
                 docs=None) -> None:
        self.path = path
        self.min_observations = min_observations
        self.avoid_above = avoid_above
        # (subject_type, subject_id, condition) -> [runs, failures]
        self.stats: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        self.patterns: dict[tuple, FailurePattern] = {}
        # this node's observations not yet added to the stored totals
        self._pending_stats: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        self._pending_patterns: dict[tuple, FailurePattern] = {}
        self._doc = None
        self._raw = None
        if path is not None:
            from hydra.core.docstore import DocumentStore

            self._doc = (docs or DocumentStore()).document("failure_memory.json", path)
        self._load()

    # ------------------------------------------------------------------ learning
    async def observe(self, event: HydraEvent) -> None:
        p = event.payload
        if event.type in (EventType.MODEL_COMPLETED, EventType.MODEL_FAILED):
            key = ("model", p.get("model", "?"), _cond(p))
            self._count(key, runs=1)
            if event.type == EventType.MODEL_FAILED:
                self._record(key, p.get("kind", "unknown"))
        elif event.type in (EventType.TOOL_COMPLETED, EventType.TOOL_FAILED):
            key = ("tool", p.get("tool", "?"), ())
            self._count(key, runs=1)
            if event.type == EventType.TOOL_FAILED and p.get("kind") in ("timeout", "tool_error"):
                self._record(key, p["kind"])

    def _count(self, key: tuple, runs: int = 0, failures: int = 0) -> None:
        for stats in (self.stats, self._pending_stats):
            stats[key][0] += runs
            stats[key][1] += failures

    def _record(self, key: tuple, kind: str) -> None:
        self._count(key, failures=1)
        pkey = (*key, kind)
        now = datetime.now(UTC)
        for patterns in (self.patterns, self._pending_patterns):
            pat = patterns.get(pkey) or FailurePattern(
                subject_type=key[0], subject_id=key[1], kind=kind, condition=dict(key[2]))
            pat.failures += 1
            pat.last_seen = now
            patterns[pkey] = pat
        self._save()

    # ------------------------------------------------------------------ querying
    def failure_rate(self, subject_type: str, subject_id: str, condition: dict | None = None) -> tuple[float, int]:
        """Failure rate under a condition (all conditions if None) and number of observations."""
        self._refresh()
        runs = fails = 0
        want = tuple((k, condition[k]) for k in CONDITION_KEYS if condition and k in condition)
        for (st, sid, cond), (r, f) in self.stats.items():
            if st != subject_type or sid != subject_id:
                continue
            if want and not set(want) <= set(cond):
                continue
            runs += r
            fails += f
        return (fails / runs if runs else 0.0), runs

    def should_avoid(self, model_id: str, condition: dict) -> bool:
        rate, n = self.failure_rate("model", model_id, condition)
        return n >= self.min_observations and rate > self.avoid_above

    def report(self) -> list[dict]:
        self._refresh()
        out = []
        for pat in sorted(self.patterns.values(), key=lambda p: -p.failures):
            key = (pat.subject_type, pat.subject_id, tuple(pat.condition.items()))
            runs = self.stats.get(key, [0, 0])[0]
            out.append({**pat.model_dump(mode="json"), "runs": runs,
                        "failure_rate": round(pat.failures / runs, 3) if runs else None})
        return out

    # ------------------------------------------------------------------ persistence
    @staticmethod
    def _parse(data: dict) -> tuple[dict[tuple, list[int]], dict[tuple, FailurePattern]]:
        stats: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        patterns: dict[tuple, FailurePattern] = {}
        for (st, sid), cond, v in data.get("stats", []):
            stats[(st, sid, tuple(tuple(c) for c in cond))] = list(v)
        for p in data.get("patterns", []):
            pat = FailurePattern.model_validate(p)
            patterns[(pat.subject_type, pat.subject_id, tuple(pat.condition.items()), pat.kind)] = pat
        return stats, patterns

    @staticmethod
    def _dump(stats: dict, patterns: dict) -> dict:
        return {"stats": [[list(k[:2]), [list(c) for c in k[2]], v] for k, v in stats.items()],
                "patterns": [p.model_dump(mode="json") for p in patterns.values()]}

    def _adopt(self, data: dict) -> None:
        """Stored totals plus this node's observations not yet stored."""
        self._raw = data
        stats, patterns = self._parse(data)
        for key, (runs, fails) in self._pending_stats.items():
            stats[key][0] += runs
            stats[key][1] += fails
        for pkey, pending in self._pending_patterns.items():
            pat = patterns.get(pkey)
            if pat is None:
                patterns[pkey] = pending.model_copy()
            else:
                pat.failures += pending.failures
                pat.last_seen = max(filter(None, (pat.last_seen, pending.last_seen)), default=None)
        self.stats, self.patterns = stats, patterns

    def _refresh(self) -> None:
        if self._doc is not None and self._doc.shared and self._doc.get() is not self._raw:
            self._adopt(self._doc.get())

    def _save(self) -> None:
        if self._doc is None:
            return
        pending_stats, pending_patterns = self._pending_stats, self._pending_patterns

        def merge(data: dict) -> dict:
            stats, patterns = self._parse(data or {})
            for key, (runs, fails) in pending_stats.items():
                stats[key][0] += runs
                stats[key][1] += fails
            for pkey, pending in pending_patterns.items():
                pat = patterns.get(pkey)
                if pat is None:
                    patterns[pkey] = pending.model_copy()
                else:
                    pat.failures += pending.failures
                    pat.last_seen = max(filter(None, (pat.last_seen, pending.last_seen)), default=None)
            return self._dump(stats, patterns)

        stored = self._doc.update(merge)
        self._pending_stats = defaultdict(lambda: [0, 0])
        self._pending_patterns = {}
        self._adopt(stored)

    def _load(self) -> None:
        if self._doc is None:
            return
        self._adopt(self._doc.get() or {})
