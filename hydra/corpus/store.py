# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Corpus store: append-only versioned log, lineage graph, tombstones and snapshots.

    corpus/
    ├── log.jsonl          every record version (latest wins; nothing is rewritten)
    ├── lineage.jsonl      parent -> child edges (record -> dataset -> training run -> model -> artifact)
    ├── tombstones.jsonl   excluded records + impact analysis
    ├── snapshots.jsonl    Corpus Time Machine (log offset + content hash)
    ├── curated/           partitioned export  year=/month=/domain=  (Parquet if pyarrow, else JSONL)
    └── releases/          frozen dataset releases (never "latest")

The four logs are ``hydra.core.eventlog`` logs: JSONL files on one node, or streams of the PostgreSQL
table ``hydra_logs`` (HYDRA_CORPUS_BACKEND) shared by every node. The in-memory state is the replay of
the logs; with a shared backend it picks up other nodes' writes at most ``refresh_s`` seconds after
them, and always before its own writes and snapshots.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from pydantic import BaseModel, Field

from hydra.core.eventlog import FileLog, LogSpace, PostgresLog
from hydra.core.hashing import hash_obj, now_iso
from hydra.corpus.dedup import ContaminationGuard, Deduplicator
from hydra.corpus.gates import CorpusCurator, GateDecision
from hydra.corpus.records import CorpusRecord, LineageEdge, Tombstone, TrainingStatus


class CorpusSnapshot(BaseModel):
    id: str
    created_at: str = Field(default_factory=now_iso)
    log_offset: int
    records: int
    content_hash: str
    parent: str | None = None


_TRAINABLE_STATES = (TrainingStatus.CURATED, TrainingStatus.GOLD)


class CorpusStore:
    def __init__(self, root: Path, curator: CorpusCurator | None = None, ledger=None,
                 logs: LogSpace | None = None, refresh_s: float = 1.0) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "releases").mkdir(exist_ok=True)
        self.logs = logs or LogSpace(label="corpus")
        self._log = self.logs.open(root / "log.jsonl", "corpus/log.jsonl")
        self._lineage = self.logs.open(root / "lineage.jsonl", "corpus/lineage.jsonl")
        self._tombs = self.logs.open(root / "tombstones.jsonl", "corpus/tombstones.jsonl")
        self._snaps = self.logs.open(root / "snapshots.jsonl", "corpus/snapshots.jsonl")
        self.ledger = ledger
        self.refresh_s = refresh_s
        self._lock = threading.RLock()
        self._records: dict[str, CorpusRecord] = {}
        self.offset = 0  # record log entries replayed
        self._edges: list[LineageEdge] = []
        self._edges_seen = 0
        self._tombstones: dict[str, Tombstone] = {}
        self._tombs_seen = 0
        self._synced_at = 0.0
        self._deduped: set[str] = set()
        self.dedup = curator.dedup if curator and curator.dedup else Deduplicator()
        self.curator = curator or CorpusCurator(dedup=self.dedup)
        if self.curator.dedup is None:
            self.curator.dedup = self.dedup
        self._catch_up(initial=True)

    # ------------------------------------------------------------------ state (replay of the logs)
    @property
    def records(self) -> dict[str, CorpusRecord]:
        self._sync()
        return self._records

    @property
    def edges(self) -> list[LineageEdge]:
        self._sync()
        return self._edges

    @property
    def tombstones(self) -> dict[str, Tombstone]:
        self._sync()
        return self._tombstones

    def _sync(self) -> None:
        """Pick up other nodes' writes (shared backends only, at most every ``refresh_s``)."""
        if self._log.shared and time.monotonic() - self._synced_at >= self.refresh_s:
            self._catch_up()

    def _catch_up(self, initial: bool = False) -> None:
        with self._lock:
            for seq, line in self._log.read(self.offset):
                rec = CorpusRecord.model_validate_json(line)
                self._records[rec.id] = rec
                self.offset = seq
                if not initial and rec.training_status in _TRAINABLE_STATES:
                    self._dedup_add(rec)
            if initial:  # the dedup index holds what is curated now, not what once was
                for rec in self._records.values():
                    if rec.training_status in _TRAINABLE_STATES:
                        self._dedup_add(rec)
            for seq, line in self._lineage.read(self._edges_seen):
                self._edges.append(LineageEdge.model_validate_json(line))
                self._edges_seen = seq
            for seq, line in self._tombs.read(self._tombs_seen):
                t = Tombstone.model_validate_json(line)
                self._tombstones[t.record_id] = t
                self._tombs_seen = seq
            self._synced_at = time.monotonic()

    def _dedup_add(self, rec: CorpusRecord) -> None:
        if rec.id not in self._deduped:
            self._deduped.add(rec.id)
            self.dedup.add(rec)

    def _append(self, log: FileLog | PostgresLog, model: BaseModel, apply: Callable[[int], None]) -> None:
        """Write one entry. A local log applies it directly; a shared one replays it in the global
        order, together with whatever other nodes wrote before it."""
        seq, _ = log.append(model.model_dump_json())
        if log.shared:
            self._catch_up()
        else:
            apply(seq)

    def history(self, after: int = 0) -> Iterator[tuple[int, str]]:
        """``(seq, JSON line)`` of every record version written after entry ``after`` (edge sync)."""
        return self._log.read(after)

    def set_contamination(self, guard: ContaminationGuard) -> None:
        self.curator.contamination = guard

    # ------------------------------------------------------------------ write
    def _write(self, rec: CorpusRecord) -> CorpusRecord:
        def apply(seq: int) -> None:
            self._records[rec.id] = rec
            self.offset = seq

        with self._lock:
            self._append(self._log, rec, apply)
        return rec

    def ingest(self, rec: CorpusRecord, curate: bool = True) -> tuple[CorpusRecord, GateDecision | None]:
        """incoming -> QUARANTINE -> gates -> CURATED/GOLD/BLOCKED/DUPLICATE."""
        decision = None
        if rec.id in self.tombstones:
            rec.training_status = TrainingStatus.TOMBSTONED
            return rec, None
        rec.training_status = TrainingStatus.QUARANTINED
        if curate:
            decision = self.curator.curate(rec)
            rec.training_status = decision.status
            rec.metadata["gate_reasons"] = decision.reasons
            if decision.status in _TRAINABLE_STATES:
                self._dedup_add(rec)
        self._write(rec)
        if self.ledger is not None and rec.training_status in (TrainingStatus.CURATED, TrainingStatus.GOLD):
            self.ledger.append("CORPUS_RECORD_CREATED", {
                "record_id": rec.id, "type": rec.record_type.value, "status": rec.training_status.value,
                "source": rec.source_type, "task": rec.source_task_id, "rights": rec.rights.model_dump(),
                "privacy": rec.privacy.action, "hash": rec.hashes.get("exact"),
                "parents": rec.provenance.get("parent_records", [])},
                object_type="corpus_record", object_id=rec.id)
        for parent in rec.provenance.get("parent_records", []):
            self.add_lineage(parent, rec.id, rec.provenance.get("transformation", "derived"))
        return rec, decision

    def review(self, record_id: str, approve: bool, reviewer: str, training_allowed: bool | None = None
               ) -> CorpusRecord:
        rec = self.records[record_id].model_copy(deep=True)
        if training_allowed is not None:
            rec.rights.training_allowed = training_allowed
        rec.metadata.setdefault("reviews", []).append({"by": reviewer, "approve": approve, "at": now_iso()})
        rec.metadata["human_reviewed"] = approve
        if approve:
            rec.training_status = TrainingStatus.GOLD if rec.quality > 0.92 else TrainingStatus.CURATED
            self._dedup_add(rec)
        else:
            rec.training_status = TrainingStatus.BLOCKED
        return self._write(rec)

    def add_lineage(self, parent: str, child: str, transformation: str) -> LineageEdge:
        e = LineageEdge(parent_id=parent, child_id=child, transformation=transformation)

        def apply(seq: int) -> None:
            self._edges.append(e)
            self._edges_seen = seq

        with self._lock:
            self._append(self._lineage, e, apply)
        return e

    # ------------------------------------------------------------------ lineage / impact
    def descendants(self, node: str) -> list[LineageEdge]:
        out, frontier, seen = [], [node], {node}
        while frontier:
            cur = frontier.pop()
            for e in self.edges:
                if e.parent_id == cur and e.child_id not in seen:
                    seen.add(e.child_id)
                    out.append(e)
                    frontier.append(e.child_id)
        return out

    def ancestors(self, node: str) -> list[LineageEdge]:
        out, frontier, seen = [], [node], {node}
        while frontier:
            cur = frontier.pop()
            for e in self.edges:
                if e.child_id == cur and e.parent_id not in seen:
                    seen.add(e.parent_id)
                    out.append(e)
                    frontier.append(e.parent_id)
        return out

    def tombstone(self, record_id: str, reason: str) -> Tombstone:
        """Exclude a record everywhere and report which datasets/models may have learned from it."""
        down = self.descendants(record_id)
        kinds: dict[str, list[str]] = {"dataset": [], "model": [], "artifact": []}
        for e in down:
            for k in kinds:
                if e.child_id.startswith(f"{k}:") or e.transformation.startswith(k):
                    kinds[k].append(e.child_id)
        t = Tombstone(record_id=record_id, reason=reason, affected_datasets=sorted(set(kinds["dataset"])),
                      affected_models=sorted(set(kinds["model"])), affected_artifacts=sorted(set(kinds["artifact"])))
        def apply(seq: int) -> None:
            self._tombstones[record_id] = t
            self._tombs_seen = seq

        with self._lock:
            self._append(self._tombs, t, apply)
            if record_id in self._records:
                rec = self._records[record_id].model_copy(deep=True)
                rec.training_status = TrainingStatus.TOMBSTONED
                self._write(rec)
        if self.ledger is not None:
            self.ledger.append("CORPUS_RECORD_TOMBSTONED", t.model_dump(), object_type="corpus_record",
                               object_id=record_id)
        return t

    # ------------------------------------------------------------------ read
    def get(self, record_id: str) -> CorpusRecord | None:
        return self.records.get(record_id)

    def search(self, *, record_type: str | list[str] | None = None, domain: str | None = None,
               language: str | None = None, capability: str | None = None, min_quality: float = 0.0,
               min_verification: float = 0.0, statuses: set[str] | None = None, text: str | None = None,
               tenant_id: str | None = None, synthetic: bool | None = None, flag: str | None = None,
               task_id: str | None = None, limit: int | None = None) -> list[CorpusRecord]:
        types = {record_type} if isinstance(record_type, str) else set(record_type or [])
        out = []
        for r in self.records.values():
            if types and r.record_type.value not in types:
                continue
            if domain and domain not in r.domain:
                continue
            if language and r.language != language:
                continue
            if capability and not any(c == capability or c.startswith(capability + ".") for c in r.capabilities):
                continue
            if r.quality < min_quality or r.verification < min_verification:
                continue
            if statuses and r.training_status.value not in statuses:
                continue
            if tenant_id is not None and r.tenant_id != tenant_id:
                continue
            if synthetic is not None and r.synthetic != synthetic:
                continue
            if flag and flag not in r.flags:
                continue
            if task_id and r.source_task_id != task_id:
                continue
            if text and text.lower() not in r.text().lower():
                continue
            out.append(r)
            if limit and len(out) >= limit:
                break
        return out

    def trainable(self) -> list[CorpusRecord]:
        return [r for r in self.records.values() if r.trainable and r.id not in self.tombstones]

    # ------------------------------------------------------------------ snapshots
    def snapshot(self) -> CorpusSnapshot:
        """Freeze the state at the current log offset. The id and parent are assigned while the
        snapshot stream is locked, so two nodes never mint the same snapshot id."""
        with self._lock:
            if self._log.shared:
                self._catch_up()
            state = sorted((r.id, r.training_status.value) for r in self._records.values())
            offset, count, day = self.offset, len(self._records), datetime.now().strftime("%Y.%m.%d")

            def build(seq: int, last: str | None) -> str:
                parent = CorpusSnapshot.model_validate_json(last).id if last else None
                return CorpusSnapshot(id=f"hc-{day}-{seq}", log_offset=offset, records=count,
                                      content_hash=hash_obj(state), parent=parent).model_dump_json()

            _, body = self._snaps.append(build)
        return CorpusSnapshot.model_validate_json(body)

    def snapshots(self) -> list[CorpusSnapshot]:
        return [CorpusSnapshot.model_validate_json(x) for _, x in self._snaps.read()]

    def at_snapshot(self, snapshot_id: str) -> dict[str, CorpusRecord]:
        snap = next(s for s in self.snapshots() if s.id == snapshot_id)
        state: dict[str, CorpusRecord] = {}
        for _, line in self._log.read(0, snap.log_offset):
            rec = CorpusRecord.model_validate_json(line)
            state[rec.id] = rec
        return state

    # ------------------------------------------------------------------ export
    def export_partitioned(self, statuses: set[str] | None = None) -> dict[str, Any]:
        """curated/year=YYYY/month=MM/domain=D/part.{parquet|jsonl}"""
        statuses = statuses or {"CURATED", "GOLD"}
        groups: dict[tuple, list[dict]] = {}
        for r in self.records.values():
            if r.training_status.value not in statuses or r.id in self.tombstones:
                continue
            y, m = r.created_at[:4], r.created_at[5:7]
            d = (r.domain or ["general"])[0]
            groups.setdefault((y, m, d), []).append(r.model_dump(mode="json"))
        written = []
        for (y, m, d), rows in groups.items():
            folder = self.root / "curated" / f"year={y}" / f"month={m}" / f"domain={d}"
            folder.mkdir(parents=True, exist_ok=True)
            written.append(str(write_table(folder / "part", rows)))
        return {"partitions": len(groups), "files": written}

    def stats(self) -> dict[str, Any]:
        recs = list(self.records.values())
        status = Counter(r.training_status.value for r in recs)
        tiers = Counter(r.tier.value for r in recs)
        langs = Counter(r.language or "unknown" for r in recs)
        domains = Counter(d for r in recs for d in (r.domain or ["general"]))
        types = Counter(r.record_type.value for r in recs)
        total = len(recs) or 1
        return {
            "records": len(recs), "status": dict(status), "tiers": dict(tiers),
            "record_types": dict(types),
            "languages": {k: round(v / total, 3) for k, v in langs.most_common()},
            "domains": {k: round(v / total, 3) for k, v in domains.most_common()},
            "synthetic_fraction": round(sum(r.synthetic for r in recs) / total, 3),
            "duplicates_removed": status.get("DUPLICATE", 0),
            "privacy_rejected": sum(1 for r in recs if r.privacy.action == "REJECT"),
            "pseudonymized": sum(1 for r in recs if r.privacy.action == "PSEUDONYMIZE"),
            "tombstones": len(self.tombstones), "lineage_edges": len(self.edges),
            "trainable": len(self.trainable()),
            "hard": sum("hard" in r.flags for r in recs), "frontier": sum("frontier" in r.flags for r in recs),
        }


def write_table(stem: Path, rows: list[dict]) -> Path:
    """Parquet when pyarrow is installed (columnar source of truth), otherwise JSONL."""
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore

        table = pa.Table.from_pylist([{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                                       for k, v in r.items()} for r in rows])
        path = stem.with_suffix(".parquet")
        pq.write_table(table, path)
        return path
    except ImportError:
        path = stem.with_suffix(".jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        return path
