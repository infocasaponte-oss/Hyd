# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Append-only, hash-chained, signed provenance/IP ledger.

    H_n = SHA256(H_{n-1} | timestamp | actor | type | canonical(payload))

Changing any past event breaks every later hash. Corrections are new events
(``EVENT_CORRECTION``) that reference the original; nothing is ever updated or deleted.
Every ``anchor_every`` events a Merkle root over the batch is stored as an anchor, so the
existence of a batch can be proven without revealing its contents.

Two backends share this contract: ``Ledger`` (JSONL files, one host) and
``hydra.ledger.pg.PostgresLedger`` (``ip_events`` / ``ledger_anchors`` in PostgreSQL, whose trigger
rejects UPDATE/DELETE; shared by every node). ``open_ledger`` picks one (``HYDRA_LEDGER_BACKEND``).
"""

from __future__ import annotations

import json
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from pydantic import BaseModel, Field

from hydra.core.hashing import canonical_json, merkle_proof, merkle_root, now_iso, sha256_hex
from hydra.ledger.signing import Signer, verify_signature

GENESIS = "0" * 64


class LedgerEventType(str, Enum):
    # ideas / inventions
    IDEA_CREATED = "IDEA_CREATED"
    INVENTION_PROPOSED = "INVENTION_PROPOSED"
    INVENTION_CANDIDATE_CREATED = "INVENTION_CANDIDATE_CREATED"
    INVENTION_STATUS_CHANGED = "INVENTION_STATUS_CHANGED"
    DESIGN_CREATED = "DESIGN_CREATED"
    DESIGN_CHANGED = "DESIGN_CHANGED"
    ARCHITECTURE_CHANGED = "ARCHITECTURE_CHANGED"
    CONTRIBUTION_RECORDED = "CONTRIBUTION_RECORDED"
    MODEL_ASSISTANCE = "MODEL_ASSISTANCE"
    PRIOR_ART_SEARCH = "PRIOR_ART_SEARCH"
    # code / experiments
    CODE_COMMIT_REGISTERED = "CODE_COMMIT_REGISTERED"
    EXPERIMENT_CREATED = "EXPERIMENT_CREATED"
    EXPERIMENT_STARTED = "EXPERIMENT_STARTED"
    EXPERIMENT_EXECUTED = "EXPERIMENT_EXECUTED"
    EXPERIMENT_COMPLETED = "EXPERIMENT_COMPLETED"
    TECHNICAL_EFFECT_OBSERVED = "TECHNICAL_EFFECT_OBSERVED"
    # data / models
    CORPUS_RECORD_CREATED = "CORPUS_RECORD_CREATED"
    CORPUS_RECORD_TOMBSTONED = "CORPUS_RECORD_TOMBSTONED"
    DATASET_CREATED = "DATASET_CREATED"
    DATASET_RELEASED = "DATASET_RELEASED"
    TRAINING_STARTED = "TRAINING_STARTED"
    TRAINING_COMPLETED = "TRAINING_COMPLETED"
    MODEL_CREATED = "MODEL_CREATED"
    MODEL_TRAINED = "MODEL_TRAINED"
    ADAPTER_CREATED = "ADAPTER_CREATED"
    MODEL_CONVERTED = "MODEL_CONVERTED"
    MODEL_QUANTIZED = "MODEL_QUANTIZED"
    MODEL_SIGNED = "MODEL_SIGNED"
    BENCHMARK_COMPLETED = "BENCHMARK_COMPLETED"
    # licenses / disclosure / patents
    LICENSE_ADDED = "LICENSE_ADDED"
    LICENSE_DETECTED = "LICENSE_DETECTED"
    LICENSE_REVIEWED = "LICENSE_REVIEWED"
    LICENSE_EXCEPTION_GRANTED = "LICENSE_EXCEPTION_GRANTED"
    DISCLOSURE_CREATED = "DISCLOSURE_CREATED"
    PUBLIC_DISCLOSURE = "PUBLIC_DISCLOSURE"
    PATENT_CANDIDATE_IDENTIFIED = "PATENT_CANDIDATE_IDENTIFIED"
    PATENT_REVIEW_STARTED = "PATENT_REVIEW_STARTED"
    PATENT_FILED = "PATENT_FILED"
    TRADE_SECRET_ACCESSED = "TRADE_SECRET_ACCESSED"
    # releases
    RELEASE_PROPOSED = "RELEASE_PROPOSED"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    RELEASE_BLOCKED = "RELEASE_BLOCKED"
    RELEASE_CREATED = "RELEASE_CREATED"
    # runtime
    TASK_EXECUTED = "TASK_EXECUTED"
    PLANNER_DECISION = "PLANNER_DECISION"
    FEDERATED_ROUND = "FEDERATED_ROUND"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    EVENT_CORRECTION = "EVENT_CORRECTION"


class LedgerEvent(BaseModel):
    sequence: int
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    created_at: str = Field(default_factory=now_iso)
    actor_type: str = "service"
    actor_id: str = "hydra"
    object_type: str = ""
    object_id: str = ""
    project_id: str = "hydra"
    payload: dict[str, Any] = Field(default_factory=dict)
    confidentiality: str = "INTERNAL_CONFIDENTIAL"
    producer: str = "hydra"
    previous_hash: str = GENESIS
    event_hash: str = ""
    signature: str | None = None
    signing_key_id: str | None = None


def event_hash(previous_hash: str, event_type: str, timestamp: str, actor: str, payload: dict) -> str:
    return sha256_hex(previous_hash + timestamp + actor + event_type + canonical_json(payload))


class LedgerAnchor(BaseModel):
    first_sequence: int
    last_sequence: int
    merkle_root: str
    created_at: str = Field(default_factory=now_iso)
    external_timestamp_ref: str | None = None


class ChainReport(BaseModel):
    ok: bool
    events: int
    broken_at: int | None = None
    reason: str = ""
    anchors_ok: bool = True
    signatures_checked: int = 0


class Ledger:
    """File-backed append-only ledger (thread-safe within a process)."""

    backend = "file"

    def __init__(self, root: Path, signer: Signer | None = None, anchor_every: int = 1000) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "events.jsonl"
        self.anchor_path = root / "anchors.jsonl"
        self.signer = signer
        self.anchor_every = anchor_every
        self._lock = threading.Lock()
        self._last_hash, self._count = GENESIS, 0
        self._by_object: dict[str, list[int]] = {}
        self._events: list[LedgerEvent] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._index(LedgerEvent.model_validate_json(line))

    def _index(self, e: LedgerEvent) -> None:
        self._events.append(e)
        self._last_hash, self._count = e.event_hash, e.sequence
        if e.object_id:
            self._by_object.setdefault(f"{e.object_type}:{e.object_id}", []).append(len(self._events) - 1)

    # ------------------------------------------------------------------ write
    def append(self, event_type: LedgerEventType | str, payload: dict[str, Any] | None = None, *,
               object_type: str = "", object_id: str = "", actor_type: str = "service", actor_id: str = "hydra",
               confidentiality: str = "INTERNAL_CONFIDENTIAL", project_id: str = "hydra",
               producer: str = "hydra") -> LedgerEvent:
        et = event_type.value if isinstance(event_type, LedgerEventType) else str(event_type)
        payload = json.loads(canonical_json(payload or {}))  # jsonable + stable
        with self._lock:
            e = LedgerEvent(sequence=self._count + 1, event_type=et, actor_type=actor_type, actor_id=actor_id,
                            object_type=object_type, object_id=object_id, project_id=project_id,
                            payload=payload, confidentiality=confidentiality, producer=producer,
                            previous_hash=self._last_hash)
            e.event_hash = event_hash(e.previous_hash, et, e.created_at, f"{actor_type}:{actor_id}", payload)
            if self.signer is not None:
                e.signature, e.signing_key_id = self.signer.sign(e.event_hash), self.signer.key_id
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(e.model_dump_json() + "\n")
            self._index(e)
            if self.anchor_every and e.sequence % self.anchor_every == 0:
                self._anchor(e.sequence - self.anchor_every + 1, e.sequence)
        return e

    def correct(self, original_event_id: str, correction: dict[str, Any], reason: str, **kw) -> LedgerEvent:
        return self.append(LedgerEventType.EVENT_CORRECTION,
                           {"corrects": original_event_id, "correction": correction, "reason": reason}, **kw)

    def _anchor(self, first: int, last: int) -> LedgerAnchor:
        hashes = [e.event_hash for e in self._events if first <= e.sequence <= last]
        a = LedgerAnchor(first_sequence=first, last_sequence=last, merkle_root=merkle_root(hashes))
        with open(self.anchor_path, "a", encoding="utf-8") as f:
            f.write(a.model_dump_json() + "\n")
        return a

    def anchor_now(self) -> LedgerAnchor | None:
        """Anchor the events since the last anchor (e.g. before a release or a backup)."""
        with self._lock:
            anchors = self.anchors()
            first = anchors[-1].last_sequence + 1 if anchors else 1
            if first > self._count:
                return None
            return self._anchor(first, self._count)

    # ------------------------------------------------------------------ read
    def __len__(self) -> int:
        return self._count

    def events(self, event_type: str | None = None) -> Iterator[LedgerEvent]:
        for e in list(self._events):
            if event_type is None or e.event_type == event_type:
                yield e

    def for_object(self, object_type: str, object_id: str) -> list[LedgerEvent]:
        return [self._events[i] for i in self._by_object.get(f"{object_type}:{object_id}", [])]

    def search(self, needle: str) -> list[LedgerEvent]:
        return [e for e in self._events if needle in e.object_id or needle in canonical_json(e.payload)]

    def anchors(self) -> list[LedgerAnchor]:
        if not self.anchor_path.exists():
            return []
        return [LedgerAnchor.model_validate_json(x) for x in self.anchor_path.read_text(encoding="utf-8").splitlines()
                if x.strip()]

    def proof(self, sequence: int) -> dict[str, Any] | None:
        """Merkle inclusion proof of one event inside its anchor."""
        return inclusion_proof(self.anchors(), sequence,
                               lambda first, last: [e.event_hash for e in self._events if first <= e.sequence <= last])

    # ------------------------------------------------------------------ verify
    def verify(self, public_keys: dict[str, str] | None = None) -> ChainReport:
        """Recompute the whole chain from disk (not from the in-memory index)."""
        events: list[LedgerEvent] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(LedgerEvent.model_validate_json(line))
        return verify_chain(events, self.anchors(), self.signer, public_keys)

    def export_jsonl(self) -> tuple[str, str]:
        """``events.jsonl`` and ``anchors.jsonl`` contents (the portable backup format)."""
        events = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        anchors = self.anchor_path.read_text(encoding="utf-8") if self.anchor_path.exists() else ""
        return events, anchors


def inclusion_proof(anchors: list[LedgerAnchor], sequence: int, hashes_between) -> dict[str, Any] | None:
    for a in anchors:
        if a.first_sequence <= sequence <= a.last_sequence:
            hashes = hashes_between(a.first_sequence, a.last_sequence)
            idx = sequence - a.first_sequence
            return {"leaf": hashes[idx], "proof": merkle_proof(hashes, idx), "root": a.merkle_root,
                    "anchor": a.model_dump()}
    return None


def verify_chain(events: list[LedgerEvent], anchors: list[LedgerAnchor], signer: Signer | None = None,
                 public_keys: dict[str, str] | None = None) -> ChainReport:
    """Recompute sequence, hash chain, signatures and Merkle anchors (shared by every backend)."""
    prev, n, checked = GENESIS, 0, 0
    keys = dict(public_keys or {})
    if signer is not None:
        keys.setdefault(signer.key_id, signer.public_pem)
    for e in events:
        n += 1
        if e.sequence != n:
            return ChainReport(ok=False, events=len(events), broken_at=e.sequence, reason="sequence gap")
        if e.previous_hash != prev:
            return ChainReport(ok=False, events=len(events), broken_at=e.sequence, reason="previous_hash mismatch")
        expected = event_hash(prev, e.event_type, e.created_at, f"{e.actor_type}:{e.actor_id}", e.payload)
        if expected != e.event_hash:
            return ChainReport(ok=False, events=len(events), broken_at=e.sequence, reason="event_hash mismatch")
        if e.signature and e.signing_key_id in keys:
            checked += 1
            if not verify_signature(keys[e.signing_key_id], e.event_hash, e.signature):
                return ChainReport(ok=False, events=len(events), broken_at=e.sequence, reason="bad signature")
        prev = e.event_hash
    anchors_ok = True
    by_seq = {e.sequence: e.event_hash for e in events}
    for a in anchors:
        hashes = [by_seq.get(s, "") for s in range(a.first_sequence, a.last_sequence + 1)]
        if "" in hashes or merkle_root(hashes) != a.merkle_root:
            anchors_ok = False
    return ChainReport(ok=anchors_ok, events=len(events), anchors_ok=anchors_ok, signatures_checked=checked,
                       reason="" if anchors_ok else "anchor mismatch")
