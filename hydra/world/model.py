# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA World Model + Belief Graph (temporal, multimodal, versioned).

    texto != memoria · imagen != descripción · documento != chunk · evento != frase

Everything becomes entities, relations, events, observations, evidence and beliefs.
An observation is never truth: the belief engine decides how much HYDRA believes it,
combining evidence by *source family* (three models fine-tuned from the same base are
not three independent witnesses). Relations are bitemporal (valid time + recorded time),
every change is a ``KnowledgeDelta`` and every delta bumps the world version, so any task
can be reproduced against the exact world it saw (World Time Machine).

The World Model is the interpretable *current* state; the IP ledger is the immutable
history. The graph may change, the ledger never does.

The delta log and the snapshots are ``hydra.core.eventlog`` logs: JSONL files on one node, or streams
of the PostgreSQL table ``hydra_logs`` (HYDRA_WORLD_BACKEND) shared by every node, which replay the
same deltas in the same order. With a shared backend a node picks up other nodes' deltas at most
``refresh_s`` seconds after them, and always before applying its own.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from hydra.core.eventlog import LogSpace
from hydra.core.hashing import hash_obj, now_iso


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def slug(text: str) -> str:
    s = re.sub(r"[^\w.:+-]+", "-", text.strip().lower(), flags=re.U).strip("-")
    return s[:120] or "unnamed"


class Visibility(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    TRADE_SECRET = "TRADE_SECRET"


VISIBILITY_RANK = {v: i for i, v in enumerate(Visibility)}


class BeliefStatus(str, Enum):
    HYPOTHESIS = "HYPOTHESIS"
    SUPPORTED = "SUPPORTED"
    VERIFIED = "VERIFIED"
    CONTESTED = "CONTESTED"
    REJECTED = "REJECTED"
    OBSOLETE = "OBSOLETE"


class EvidenceType(str, Enum):
    DOCUMENT = "DOCUMENT"
    TOOL_RESULT = "TOOL_RESULT"
    UNIT_TEST = "UNIT_TEST"
    IMAGE_OBSERVATION = "IMAGE_OBSERVATION"
    VIDEO_EVENT = "VIDEO_EVENT"
    DATABASE_QUERY = "DATABASE_QUERY"
    MODEL_CONSENSUS = "MODEL_CONSENSUS"
    MODEL = "MODEL"
    HUMAN_CONFIRMATION = "HUMAN_CONFIRMATION"
    EXPERIMENT = "EXPERIMENT"
    USER_INPUT = "USER_INPUT"
    MEMORY = "MEMORY"


DEFAULT_STRENGTH = {
    EvidenceType.UNIT_TEST: 0.95, EvidenceType.HUMAN_CONFIRMATION: 0.95, EvidenceType.TOOL_RESULT: 0.9,
    EvidenceType.DATABASE_QUERY: 0.9, EvidenceType.EXPERIMENT: 0.9, EvidenceType.DOCUMENT: 0.7,
    EvidenceType.USER_INPUT: 0.7, EvidenceType.MEMORY: 0.65, EvidenceType.MODEL_CONSENSUS: 0.6,
    EvidenceType.IMAGE_OBSERVATION: 0.6, EvidenceType.VIDEO_EVENT: 0.6, EvidenceType.MODEL: 0.5,
}
STRONG_EVIDENCE = {EvidenceType.UNIT_TEST, EvidenceType.HUMAN_CONFIRMATION, EvidenceType.TOOL_RESULT,
                   EvidenceType.DATABASE_QUERY, EvidenceType.EXPERIMENT}

FUNCTIONAL_PREDICATES = {"port", "puerto", "version", "status", "deployed_on", "capital", "owner", "located_in",
                         "is", "es", "value", "valor", "uses_port", "runs_on", "current_model"}
"""Predicates with a single valid value at a time: a new value closes (or contests) the old one."""

VOLATILE_DECAY = {"load": 0.5, "queue": 0.5, "status": 0.05, "free_vram": 0.5, "price": 0.2, "weather": 0.1}
"""Confidence decay per hour (C(t) = C0·e^(-λt)) for predicates whose truth ages quickly."""


class WorldEntity(BaseModel):
    id: str
    entity_type: str = "entity"
    canonical_name: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    confidence: float = 0.6
    provenance_refs: list[str] = Field(default_factory=list)
    visibility: Visibility = Visibility.INTERNAL


class WorldRelation(BaseModel):
    id: str = Field(default_factory=lambda: _id("rel"))
    subject_id: str
    predicate: str
    object_id: str
    valid_from: str | None = Field(default_factory=now_iso)
    valid_until: str | None = None
    recorded_at: str = Field(default_factory=now_iso)
    confidence: float = 0.6
    evidence_ids: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)

    def valid_at(self, t: float) -> bool:
        return _ts(self.valid_from) <= t and (self.valid_until is None or t < _ts(self.valid_until))


class WorldEvent(BaseModel):
    id: str = Field(default_factory=lambda: _id("evt"))
    event_type: str
    started_at: str = Field(default_factory=now_iso)
    ended_at: str | None = None
    participants: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    recorded_at: str = Field(default_factory=now_iso)


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: _id("obs"))
    observer: str
    modality: str = "text"
    statement: str
    subject: str | None = None
    predicate: str | None = None
    value: Any = None
    confidence: float = 0.6
    timestamp: str = Field(default_factory=now_iso)
    source_ref: str = ""
    source_family: str | None = None
    evidence_type: EvidenceType = EvidenceType.MODEL
    bbox: list[float] | None = None


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: _id("ev"))
    evidence_type: EvidenceType
    source_id: str
    source_family: str
    """Independence group: evidence from the same family counts once (max strength)."""
    content_hash: str = ""
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
    strength: float = 0.6
    timestamp: str = Field(default_factory=now_iso)
    provenance: dict[str, Any] = Field(default_factory=dict)


class Belief(BaseModel):
    id: str = Field(default_factory=lambda: _id("bel"))
    proposition: str
    subject_id: str | None = None
    predicate: str | None = None
    object_value: Any = None
    confidence: float = 0.5
    status: BeliefStatus = BeliefStatus.HYPOTHESIS
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    valid_from: str | None = Field(default_factory=now_iso)
    valid_until: str | None = None
    recorded_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    decay_rate: float = 0.0
    visibility: Visibility = Visibility.INTERNAL

    def effective_confidence(self, now: float | None = None) -> float:
        if not self.decay_rate:
            return self.confidence
        hours = max(0.0, ((now or datetime.now(UTC).timestamp()) - _ts(self.updated_at)) / 3600)
        return self.confidence * math.exp(-self.decay_rate * hours)

    def age_seconds(self, now: float | None = None) -> float:
        return (now or datetime.now(UTC).timestamp()) - _ts(self.updated_at)


class CausalStatus(str, Enum):
    CORRELATED = "CORRELATED"
    TEMPORALLY_PRECEDES = "TEMPORALLY_PRECEDES"
    CANDIDATE_CAUSE = "CANDIDATE_CAUSE"
    SUPPORTED_CAUSE = "SUPPORTED_CAUSE"


class CausalLink(BaseModel):
    id: str = Field(default_factory=lambda: _id("cause"))
    cause: str
    effect: str
    status: CausalStatus = CausalStatus.CORRELATED
    interventions: int = 0
    observations: int = 1
    evidence_ids: list[str] = Field(default_factory=list)


class KnowledgeDelta(BaseModel):
    entities_created: list[WorldEntity] = Field(default_factory=list)
    entities_updated: list[WorldEntity] = Field(default_factory=list)
    relations_added: list[WorldRelation] = Field(default_factory=list)
    relations_closed: list[str] = Field(default_factory=list)
    beliefs_added: list[Belief] = Field(default_factory=list)
    beliefs_updated: list[Belief] = Field(default_factory=list)
    events_added: list[WorldEvent] = Field(default_factory=list)
    evidence_added: list[Evidence] = Field(default_factory=list)
    causal_links: list[CausalLink] = Field(default_factory=list)
    source: str = "hydra"
    closed_at: str | None = None
    """When ``relations_closed`` took effect. ``WorldModel.apply`` stamps it, so every replay (restart,
    another node, the time machine) closes those relations at the same instant."""

    @property
    def empty(self) -> bool:
        return not any((self.entities_created, self.entities_updated, self.relations_added, self.relations_closed,
                        self.beliefs_added, self.beliefs_updated, self.events_added, self.evidence_added,
                        self.causal_links))


class WorldSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: _id("snap"))
    world_version: int
    created_at: str = Field(default_factory=now_iso)
    graph_hash: str
    entity_versions: dict[str, str] = Field(default_factory=dict)
    corpus_version: str | None = None


# =========================================================================================
class BeliefEngine:
    """Probabilistic-style confidence with source-correlation awareness."""

    @staticmethod
    def combine(evidence: list[Evidence]) -> float:
        families: dict[str, float] = {}
        for e in evidence:
            families[e.source_family] = max(families.get(e.source_family, 0.0), e.strength)
        p = 1.0
        for s in families.values():
            p *= 1 - min(max(s, 0.0), 0.999)
        return 1 - p

    def score(self, supporting: list[Evidence], contradicting: list[Evidence]) -> tuple[float, BeliefStatus]:
        pos, neg = self.combine(supporting), self.combine(contradicting)
        conf = round(pos * (1 - neg), 4)
        strong = any(e.evidence_type in STRONG_EVIDENCE and e.strength >= 0.85 for e in supporting)
        if neg > pos and neg >= 0.5:
            return conf, BeliefStatus.REJECTED
        if conf >= 0.9 and strong:
            return conf, BeliefStatus.VERIFIED
        if conf >= 0.6:
            return conf, BeliefStatus.SUPPORTED
        return conf, BeliefStatus.HYPOTHESIS


class WorldModel:
    """World graph replayed from a durable delta log (``deltas.jsonl``), with snapshots.
    ``WorldModel(None)`` is an in-memory scratch world (never persisted)."""

    def __init__(self, root: Path | None = None, logs: LogSpace | None = None, refresh_s: float = 1.0) -> None:
        self.root = root
        self.refresh_s = refresh_s
        self._entities: dict[str, WorldEntity] = {}
        self._relations: dict[str, WorldRelation] = {}
        self._events: dict[str, WorldEvent] = {}
        self._beliefs: dict[str, Belief] = {}
        self._evidence: dict[str, Evidence] = {}
        self._causal: dict[str, CausalLink] = {}
        self._aliases: dict[str, str] = {}
        self._version = 0
        self._synced_at = 0.0
        self.engine = BeliefEngine()
        self._lock = threading.RLock()
        self.logs = self._deltas = self._snaps = None
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
            self.logs = logs or LogSpace(label="world")
            self._deltas = self.logs.open(root / "deltas.jsonl", "world/deltas.jsonl")
            self._snaps = self.logs.open(root / "snapshots.jsonl", "world/snapshots.jsonl")
            self._catch_up()

    # ------------------------------------------------------------------ state (replay of the delta log)
    @property
    def entities(self) -> dict[str, WorldEntity]:
        self._sync()
        return self._entities

    @property
    def relations(self) -> dict[str, WorldRelation]:
        self._sync()
        return self._relations

    @property
    def events(self) -> dict[str, WorldEvent]:
        self._sync()
        return self._events

    @property
    def beliefs(self) -> dict[str, Belief]:
        self._sync()
        return self._beliefs

    @property
    def evidence(self) -> dict[str, Evidence]:
        self._sync()
        return self._evidence

    @property
    def causal(self) -> dict[str, CausalLink]:
        self._sync()
        return self._causal

    @property
    def aliases(self) -> dict[str, str]:
        self._sync()
        return self._aliases

    @property
    def version(self) -> int:
        """Deltas applied: the world version every task and snapshot refers to."""
        self._sync()
        return self._version

    def _sync(self) -> None:
        """Pick up other nodes' deltas (shared backends only, at most every ``refresh_s``)."""
        if self._deltas is not None and self._deltas.shared \
                and time.monotonic() - self._synced_at >= self.refresh_s:
            self._catch_up()

    def _catch_up(self) -> None:
        with self._lock:
            for _, line in self._deltas.read(self._version):
                self._apply(KnowledgeDelta.model_validate_json(line))
            self._synced_at = time.monotonic()

    def history(self, after: int = 0) -> list[dict[str, Any]]:
        """Deltas after world version ``after``, oldest first (edge sync)."""
        if self._deltas is None:
            return []
        return [json.loads(line) for _, line in self._deltas.read(after)]

    def scratch(self) -> WorldModel:
        """In-memory copy of the current state for what-if reasoning; nothing it applies is persisted."""
        with self._lock:
            self._sync()
            w = WorldModel(None)
            w._entities, w._relations, w._events = dict(self._entities), dict(self._relations), dict(self._events)
            w._beliefs, w._evidence, w._causal = dict(self._beliefs), dict(self._evidence), dict(self._causal)
            w._aliases, w._version = dict(self._aliases), self._version
            return w

    # ------------------------------------------------------------------ apply
    def apply(self, delta: KnowledgeDelta) -> int:
        """Persist ``delta`` and apply it. On a shared log it is applied in the global order, after
        whatever other nodes appended before it; the returned version includes them."""
        if delta.empty:
            return self.version
        if delta.relations_closed and delta.closed_at is None:
            delta = delta.model_copy(update={"closed_at": now_iso()})
        with self._lock:
            if self._deltas is None:
                self._apply(delta)
            else:
                self._deltas.append(delta.model_dump_json())
                if self._deltas.shared:
                    self._catch_up()
                else:
                    self._apply(delta)
            return self._version

    def _apply(self, d: KnowledgeDelta) -> None:
        for e in [*d.entities_created, *d.entities_updated]:
            self._entities[e.id] = e
            for a in [e.id, e.canonical_name or "", *e.aliases]:
                if a:
                    self._aliases[self.norm(a)] = e.id
        closed_at = d.closed_at or now_iso()  # deltas logged before closed_at existed
        for rid in d.relations_closed:
            if rid in self._relations and self._relations[rid].valid_until is None:
                self._relations[rid] = self._relations[rid].model_copy(update={"valid_until": closed_at})
        for r in d.relations_added:
            self._relations[r.id] = r
        for ev in d.evidence_added:
            self._evidence[ev.id] = ev
        for b in [*d.beliefs_added, *d.beliefs_updated]:
            self._beliefs[b.id] = b
        for w in d.events_added:
            self._events[w.id] = w
        for c in d.causal_links:
            self._causal[c.id] = c
        self._version += 1

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def norm(name: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s.:/+-]", "", name.lower(), flags=re.U)).strip()

    def lookup(self, name: str) -> WorldEntity | None:
        eid = self.aliases.get(self.norm(name))
        return self.entities.get(eid) if eid else self.entities.get(name)

    def entity_delta(self, name: str, entity_type: str = "entity", source: str = "", confidence: float = 0.6,
                     visibility: Visibility = Visibility.INTERNAL, entity_id: str | None = None,
                     **attributes: Any) -> tuple[WorldEntity, bool]:
        """Return (entity, created) without applying (callers batch into a delta)."""
        existing = self.lookup(entity_id or name)
        if existing is not None:
            e = existing.model_copy(deep=True)
            e.attributes.update(attributes)
            e.confidence = max(e.confidence, confidence)
            e.updated_at = now_iso()
            if source and source not in e.provenance_refs:
                e.provenance_refs.append(source)
            if name not in e.aliases and self.norm(name) != self.norm(e.canonical_name or ""):
                e.aliases.append(name)
            return e, False
        eid = entity_id or f"{entity_type}/{slug(name)}"
        return WorldEntity(id=eid, entity_type=entity_type, canonical_name=name, attributes=dict(attributes),
                           confidence=confidence, provenance_refs=[source] if source else [],
                           visibility=visibility), True

    def current_relations(self, subject_id: str | None = None, predicate: str | None = None,
                          object_id: str | None = None, at: str | None = None) -> list[WorldRelation]:
        t = _ts(at) if at else None
        out = []
        for r in self.relations.values():
            if subject_id and r.subject_id != subject_id:
                continue
            if predicate and r.predicate != predicate:
                continue
            if object_id and r.object_id != object_id:
                continue
            if t is not None:
                if not r.valid_at(t):
                    continue
            elif r.valid_until is not None:
                continue
            out.append(r)
        return out

    # ------------------------------------------------------------------ belief updates
    def observe(self, obs: Observation, visibility: Visibility = Visibility.INTERNAL) -> KnowledgeDelta:
        """Turn an observation into evidence and (re)score the matching belief."""
        delta = KnowledgeDelta(source=obs.observer)
        subj_id = None
        if obs.subject:
            ent, created = self.entity_delta(obs.subject, source=obs.source_ref or obs.observer)
            (delta.entities_created if created else delta.entities_updated).append(ent)
            subj_id = ent.id
        strength = obs.confidence if obs.confidence else DEFAULT_STRENGTH[obs.evidence_type]
        strength = min(strength, DEFAULT_STRENGTH[obs.evidence_type] + 0.05)
        ev = Evidence(evidence_type=obs.evidence_type, source_id=obs.source_ref or obs.observer,
                      source_family=obs.source_family or obs.observer, content_hash=hash_obj(obs.statement),
                      strength=round(strength, 4), provenance={"observation": obs.id, "modality": obs.modality})
        delta.evidence_added.append(ev)
        pred = (obs.predicate or "").lower() or None
        value = obs.value if obs.value is not None else obs.statement
        # find the belief for exactly this proposition
        same = next((b for b in self.beliefs.values() if b.subject_id == subj_id and b.predicate == pred
                     and str(b.object_value).lower() == str(value).lower() and b.status != BeliefStatus.OBSOLETE),
                    None)
        belief = same.model_copy(deep=True) if same else Belief(
            proposition=obs.statement, subject_id=subj_id, predicate=pred, object_value=value,
            decay_rate=VOLATILE_DECAY.get(pred or "", 0.0), visibility=visibility)
        ev.supports.append(belief.id)
        belief.supporting_evidence.append(ev.id)
        pool = {**self.evidence, ev.id: ev}
        # functional predicate with a different value -> evidence contradicts rivals
        rivals = []
        if subj_id and pred and pred in FUNCTIONAL_PREDICATES:
            rivals = [b.model_copy(deep=True) for b in self.beliefs.values()
                      if b.subject_id == subj_id and b.predicate == pred and b.id != belief.id
                      and str(b.object_value).lower() != str(value).lower()
                      and b.status not in (BeliefStatus.OBSOLETE, BeliefStatus.REJECTED)]
        self._rescore(belief, pool)
        for r in rivals:
            self._rescore(r, pool)
        if rivals:
            best = max([belief, *rivals], key=lambda b: b.confidence)
            for b in [belief, *rivals]:
                if b is best:
                    continue
                if best.status == BeliefStatus.VERIFIED and best.confidence - b.confidence >= 0.15:
                    b.status, b.valid_until = BeliefStatus.OBSOLETE, now_iso()
                elif abs(best.confidence - b.confidence) < 0.25:
                    b.status = BeliefStatus.CONTESTED
                    if best.status != BeliefStatus.VERIFIED:
                        best.status = BeliefStatus.CONTESTED
            delta.beliefs_updated.extend(rivals)
        belief.updated_at = now_iso()
        (delta.beliefs_updated if same else delta.beliefs_added).append(belief)
        # functional relations: close the old edge, add the new one
        if subj_id and pred and belief.status in (BeliefStatus.SUPPORTED, BeliefStatus.VERIFIED):
            obj, created = self.entity_delta(str(value), entity_type="value", source=ev.id)
            if created:
                delta.entities_created.append(obj)
            current = self.current_relations(subj_id, pred)
            if not any(r.object_id == obj.id for r in current):
                if pred in FUNCTIONAL_PREDICATES:
                    delta.relations_closed.extend(r.id for r in current)
                delta.relations_added.append(WorldRelation(subject_id=subj_id, predicate=pred, object_id=obj.id,
                                                           confidence=belief.confidence, evidence_ids=[ev.id]))
        return delta

    def _rescore(self, belief: Belief, pool: dict[str, Evidence]) -> None:
        sup = [pool[i] for i in belief.supporting_evidence if i in pool]
        con = [pool[i] for i in belief.contradicting_evidence if i in pool]
        belief.confidence, status = self.engine.score(sup, con)
        if belief.status not in (BeliefStatus.OBSOLETE,):
            belief.status = status

    def confirm(self, belief_id: str, by: str = "human", correct: bool = True) -> KnowledgeDelta:
        b = self.beliefs[belief_id].model_copy(deep=True)
        ev = Evidence(evidence_type=EvidenceType.HUMAN_CONFIRMATION, source_id=by, source_family=f"human:{by}",
                      strength=0.97, supports=[b.id] if correct else [], contradicts=[] if correct else [b.id])
        (b.supporting_evidence if correct else b.contradicting_evidence).append(ev.id)
        self._rescore(b, {**self.evidence, ev.id: ev})
        return KnowledgeDelta(evidence_added=[ev], beliefs_updated=[b], source=by)

    # ------------------------------------------------------------------ queries
    def beliefs_about(self, subject: str, predicate: str | None = None, include_obsolete: bool = False,
                      max_age_s: float | None = None) -> list[Belief]:
        ent = self.lookup(subject)
        sid = ent.id if ent else subject
        now = datetime.now(UTC).timestamp()
        out = [b for b in self.beliefs.values() if b.subject_id == sid and (predicate is None or b.predicate == predicate)
               and (include_obsolete or b.status != BeliefStatus.OBSOLETE)
               and (max_age_s is None or b.age_seconds(now) <= max_age_s)]
        return sorted(out, key=lambda b: -b.effective_confidence(now))

    def stale(self, max_age_s: float, predicate: str | None = None) -> list[Belief]:
        """Beliefs that need a refresh before a planner may rely on them (freshness requirements)."""
        now = datetime.now(UTC).timestamp()
        return [b for b in self.beliefs.values() if (predicate is None or b.predicate == predicate)
                and b.status != BeliefStatus.OBSOLETE and b.age_seconds(now) > max_age_s]

    def conflicts(self) -> list[list[Belief]]:
        groups: dict[tuple, list[Belief]] = {}
        for b in self.beliefs.values():
            if b.status == BeliefStatus.CONTESTED:
                groups.setdefault((b.subject_id, b.predicate), []).append(b)
        return list(groups.values())

    def neighbors(self, entity_id: str, depth: int = 1, at: str | None = None) -> dict[str, Any]:
        seen, frontier, edges = {entity_id}, {entity_id}, []
        for _ in range(depth):
            nxt = set()
            for r in (self.current_relations(at=at)):
                if r.subject_id in frontier or r.object_id in frontier:
                    edges.append(r)
                    for x in (r.subject_id, r.object_id):
                        if x not in seen:
                            seen.add(x)
                            nxt.add(x)
            frontier = nxt
        return {"nodes": [self.entities[i].model_dump() for i in seen if i in self.entities],
                "edges": [e.model_dump() for e in {e.id: e for e in edges}.values()]}

    def path(self, source: str, target: str, max_depth: int = 6) -> list[WorldRelation]:
        """Shortest relation path (BFS over current relations, both directions)."""
        a, b = (self.lookup(source) or WorldEntity(id=source)).id, (self.lookup(target) or WorldEntity(id=target)).id
        prev: dict[str, tuple[str, WorldRelation]] = {}
        frontier, seen = [a], {a}
        rels = self.current_relations()
        for _ in range(max_depth):
            nxt = []
            for node in frontier:
                for r in rels:
                    other = r.object_id if r.subject_id == node else r.subject_id if r.object_id == node else None
                    if other and other not in seen:
                        seen.add(other)
                        prev[other] = (node, r)
                        nxt.append(other)
                        if other == b:
                            out, cur = [], b
                            while cur != a:
                                cur, rel = prev[cur][0], prev[cur][1]
                                out.append(rel)
                            return list(reversed(out))
            frontier = nxt
        return []

    def events_between(self, start: str | None = None, end: str | None = None,
                       participant: str | None = None) -> list[WorldEvent]:
        s, e = _ts(start) if start else 0, _ts(end) if end else float("inf")
        return sorted([w for w in self.events.values() if s <= _ts(w.started_at) <= e
                       and (participant is None or participant in w.participants)],
                      key=lambda w: w.started_at)

    # ------------------------------------------------------------------ causality
    def record_intervention(self, cause_event: str, effect_event: str, before: dict, after: dict,
                            intervention: dict) -> KnowledgeDelta:
        link = next((c for c in self.causal.values() if c.cause == cause_event and c.effect == effect_event), None)
        link = link.model_copy(deep=True) if link else CausalLink(cause=cause_event, effect=effect_event)
        link.interventions += 1
        changed = any(before.get(k) != after.get(k) for k in set(before) | set(after))
        if changed:
            link.status = CausalStatus.SUPPORTED_CAUSE if link.interventions >= 2 else CausalStatus.CANDIDATE_CAUSE
        ev = Evidence(evidence_type=EvidenceType.EXPERIMENT, source_id="intervention", source_family="experiment",
                      strength=0.9 if changed else 0.3,
                      provenance={"intervention": intervention, "before": before, "after": after})
        link.evidence_ids.append(ev.id)
        return KnowledgeDelta(causal_links=[link], evidence_added=[ev], source="causal")

    def observe_sequence(self, first: WorldEvent, second: WorldEvent) -> KnowledgeDelta:
        if _ts(first.started_at) > _ts(second.started_at):
            first, second = second, first
        link = next((c for c in self.causal.values() if c.cause == first.id and c.effect == second.id), None)
        link = link.model_copy(deep=True) if link else CausalLink(cause=first.id, effect=second.id)
        link.observations += 1
        if link.status == CausalStatus.CORRELATED:
            link.status = CausalStatus.TEMPORALLY_PRECEDES
        return KnowledgeDelta(causal_links=[link], source="causal")

    # ------------------------------------------------------------------ versions
    def snapshot(self, corpus_version: str | None = None) -> WorldSnapshot:
        ents = {k: v.updated_at for k, v in self.entities.items()}
        graph = {"e": ents, "r": sorted(self.relations), "b": {k: (v.status, v.confidence) for k, v in self.beliefs.items()}}
        snap = WorldSnapshot(world_version=self.version, graph_hash=hash_obj(graph), entity_versions=ents,
                             corpus_version=corpus_version)
        if self._snaps is not None:
            self._snaps.append(snap.model_dump_json())
        return snap

    def snapshots(self) -> list[WorldSnapshot]:
        return [] if self._snaps is None else [WorldSnapshot.model_validate_json(x) for _, x in self._snaps.read()]

    def at_version(self, version: int) -> WorldModel:
        """Rebuild the world exactly as it was after ``version`` deltas (World Time Machine)."""
        past = WorldModel(None)
        if self._deltas is not None:
            for _, line in self._deltas.read(0, version):
                past._apply(KnowledgeDelta.model_validate_json(line))
        return past

    def stats(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for b in self.beliefs.values():
            by_status[b.status.value] = by_status.get(b.status.value, 0) + 1
        types: dict[str, int] = {}
        for e in self.entities.values():
            types[e.entity_type] = types.get(e.entity_type, 0) + 1
        return {"version": self.version, "entities": len(self.entities), "entity_types": types,
                "relations": len(self.relations),
                "current_relations": sum(1 for r in self.relations.values() if r.valid_until is None),
                "events": len(self.events), "beliefs": len(self.beliefs), "belief_status": by_status,
                "evidence": len(self.evidence), "causal_links": len(self.causal), "conflicts": len(self.conflicts())}

    def export(self) -> dict[str, Any]:
        return json.loads(json.dumps({
            "version": self.version,
            "entities": [e.model_dump() for e in self.entities.values()],
            "relations": [r.model_dump() for r in self.relations.values()],
            "beliefs": [b.model_dump() for b in self.beliefs.values()],
            "events": [w.model_dump() for w in self.events.values()],
        }, default=str))
