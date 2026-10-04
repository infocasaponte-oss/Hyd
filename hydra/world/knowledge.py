# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Knowledge Compiler, Entity Resolution, Graph RAG, Code Graph and Runtime Graph.

    raw observations + corpus + memory + tool results  ->  KnowledgeDelta
    query -> seed entities -> graph expansion -> temporal/confidence/rights filters -> ContextPacket
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.vectors import cosine as _cos
from hydra.world.model import (
    VISIBILITY_RANK,
    Belief,
    BeliefStatus,
    EvidenceType,
    KnowledgeDelta,
    Observation,
    Visibility,
    WorldEvent,
    WorldModel,
    WorldRelation,
)

TOKEN = re.compile(r"[\w.:/+-]{3,}", re.U)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in TOKEN.findall(text)}


# =========================================================================================
class EntityCandidate(BaseModel):
    entity_id: str | None
    name: str
    probability: float


class EntityResolver:
    """mention -> exact alias -> metadata -> lexical/embedding similarity -> graph context."""

    def __init__(self, world: WorldModel, embed=None, threshold: float = 0.6) -> None:
        self.world = world
        self.embed = embed  # optional callable text -> list[float]
        self.threshold = threshold

    def candidates(self, mention: str, context: str = "", k: int = 3) -> list[EntityCandidate]:
        exact = self.world.lookup(mention)
        if exact is not None:
            return [EntityCandidate(entity_id=exact.id, name=exact.canonical_name or exact.id, probability=0.97),
                    EntityCandidate(entity_id=None, name="other", probability=0.03)]
        m_tok, c_tok = _tokens(mention), _tokens(context)
        scored = []
        for e in self.world.entities.values():
            names = [e.canonical_name or "", e.id, *e.aliases]
            lex = max((len(m_tok & _tokens(n)) / max(1, len(m_tok | _tokens(n))) for n in names if n), default=0)
            ctx = len(c_tok & _tokens(" ".join(map(str, e.attributes.values())) + " " + " ".join(names))) / 10
            s = lex + min(ctx, 0.3)
            if self.embed is not None and lex > 0:
                s += 0.2 * _cos(self.embed(mention), self.embed(e.canonical_name or e.id))
            if s > 0.15:
                scored.append((s, e))
        scored.sort(key=lambda x: -x[0])
        top = scored[:k]
        weights = [math.exp(4 * s) for s, _ in top] + [math.exp(4 * 0.35)]  # "other" pseudo-candidate
        z = sum(weights)
        out = [EntityCandidate(entity_id=e.id, name=e.canonical_name or e.id, probability=round(w / z, 4))
               for (s, e), w in zip(top, weights)]
        out.append(EntityCandidate(entity_id=None, name="other", probability=round(weights[-1] / z, 4)))
        return out

    def resolve(self, mention: str, context: str = "") -> str | None:
        best = self.candidates(mention, context)[0]
        return best.entity_id if best.entity_id and best.probability >= self.threshold else None




# =========================================================================================
class PromotionPolicy(BaseModel):
    """Which task knowledge may become world knowledge (and how visible it is)."""

    min_claim_confidence: float = 0.7
    promote_statuses: set[str] = Field(default_factory=lambda: {"supported", "verified"})
    max_sensitivity_for_internal: int = 1  # INTERNAL; CONFIDENTIAL+ become CONFIDENTIAL visibility

    def visibility(self, sensitivity: int) -> Visibility:
        if sensitivity >= 3:
            return Visibility.TRADE_SECRET
        return Visibility.INTERNAL if sensitivity <= self.max_sensitivity_for_internal else Visibility.CONFIDENTIAL


SOURCE_TYPE_TO_EVIDENCE = {"tool_result": EvidenceType.TOOL_RESULT, "memory": EvidenceType.MEMORY,
                           "user_input": EvidenceType.USER_INPUT, "document": EvidenceType.DOCUMENT,
                           "judge_fact": EvidenceType.MODEL_CONSENSUS, "model": EvidenceType.MODEL}


class KnowledgeCompiler:
    def __init__(self, world: WorldModel, policy: PromotionPolicy | None = None, family_of=None) -> None:
        self.world = world
        self.policy = policy or PromotionPolicy()
        self.family_of = family_of or (lambda model_id: model_id)
        """Maps a model id to its base-model family (source correlation)."""

    def compile_task(self, *, task_id: str, objective: str, task_type: str, world_state: dict | None,
                     claims: list[dict], provenance: list[dict], models: list[str], tools: list[str],
                     artifacts: list[str], sensitivity: int, verified: bool, confidence: float,
                     tool_results: list[dict] | None = None) -> KnowledgeDelta:
        vis = self.policy.visibility(sensitivity)
        delta = KnowledgeDelta(source=f"task:{task_id}")
        # 1) the task itself is an event with participants/inputs/outputs
        task_ent, _ = self.world.entity_delta(f"task {task_id}", entity_type="task", entity_id=f"task/{task_id}",
                                              source=task_id, visibility=vis, task_type=task_type,
                                              confidence_final=confidence, verified=verified)
        delta.entities_created.append(task_ent)
        participants = [task_ent.id]
        for m in models:
            e, created = self.world.entity_delta(m, entity_type="model", entity_id=f"model/{m}", source=task_id)
            (delta.entities_created if created else delta.entities_updated).append(e)
            participants.append(e.id)
            delta.relations_added.append(WorldRelation(subject_id=task_ent.id, predicate="USED_MODEL", object_id=e.id,
                                                       confidence=1.0, valid_until=None))
        for t in tools:
            e, created = self.world.entity_delta(t, entity_type="tool", entity_id=f"tool/{t}", source=task_id)
            (delta.entities_created if created else delta.entities_updated).append(e)
            participants.append(e.id)
            delta.relations_added.append(WorldRelation(subject_id=task_ent.id, predicate="USED_TOOL", object_id=e.id,
                                                       confidence=1.0))
        delta.events_added.append(WorldEvent(event_type="TASK_EXECUTED", participants=participants,
                                             inputs=[f"objective:{objective[:200]}"], outputs=artifacts,
                                             properties={"task_type": task_type, "confidence": confidence,
                                                         "verified": verified}))
        # 2) per-task world state (text facts, perception, tool facts) as observations
        interim = self.world.scratch()

        def feed(obs: Observation) -> None:
            d = interim.observe(obs, visibility=vis)
            interim._apply(d)
            _merge(delta, d)

        for r in (world_state or {}).get("relations", []):
            src = r.get("source", "")
            et = (EvidenceType.IMAGE_OBSERVATION if src.startswith("vision:") else
                  EvidenceType.TOOL_RESULT if src.startswith("tool:") else
                  EvidenceType.MEMORY if src.startswith("memory:") else EvidenceType.USER_INPUT)
            feed(Observation(observer=src or "task", modality="image" if et == EvidenceType.IMAGE_OBSERVATION else "text",
                             statement=f"{r['subject']} {r['predicate']} {r['object']}", subject=r["subject"],
                             predicate=r["predicate"], value=r["object"], confidence=float(r.get("confidence", 0.6)),
                             source_ref=src, source_family=src.split(":")[0] if src else "task", evidence_type=et))
        # 3) claims -> beliefs, with evidence from provenance sources
        prov = {p.get("claim_id"): p for p in provenance}
        for c in claims:
            status = c.get("status", "unverified")
            if status not in self.policy.promote_statuses or c.get("confidence", 0) < self.policy.min_claim_confidence:
                continue
            p = prov.get(c.get("id"), {})
            sources = p.get("sources", []) or [{"type": "model", "ref": models[0] if models else "?"}]
            for s in sources[:4]:
                et = SOURCE_TYPE_TO_EVIDENCE.get(s.get("type", "model"), EvidenceType.MODEL)
                fam = self.family_of(s.get("ref", "?")) if et == EvidenceType.MODEL else f"{s.get('type')}:{s.get('ref')}"
                strength = max(float(s.get("strength", 0.0)), 0.5 if et == EvidenceType.MODEL else 0.6)
                if et == EvidenceType.MODEL:
                    strength = min(strength, float(c.get("confidence", 0.6)))
                feed(Observation(observer=s.get("ref", "model"), statement=c["text"][:500], subject=None,
                                 predicate=None, value=c["text"][:500], confidence=strength,
                                 source_ref=str(s.get("ref", "")), source_family=fam, evidence_type=et))
        # 4) structured tool facts: python exit codes / tests as experiments
        for r in tool_results or []:
            res = r.get("result")
            if isinstance(res, dict) and "exit_code" in res:
                delta.events_added.append(WorldEvent(event_type=f"TOOL:{r.get('tool')}", participants=[task_ent.id],
                                                     properties={"exit_code": res.get("exit_code")}))
        return delta

    def promote_corpus_record(self, record: dict) -> KnowledgeDelta:
        """Knowledge Promotion Policy for corpus -> world (quality + rights.allow_internal_knowledge)."""
        if record.get("quality", 0) < 0.95 or not record.get("rights", {}).get("allow_internal_knowledge", False):
            return KnowledgeDelta()
        content = record.get("content", {})
        subj, pred, obj = content.get("subject"), content.get("predicate"), content.get("object")
        if not (subj and pred and obj):
            return KnowledgeDelta()
        return self.world.observe(Observation(observer="corpus", statement=f"{subj} {pred} {obj}", subject=subj,
                                              predicate=pred, value=obj, confidence=0.8,
                                              source_ref=str(record.get("id")), source_family="corpus",
                                              evidence_type=EvidenceType.DOCUMENT))


def _merge(into: KnowledgeDelta, d: KnowledgeDelta) -> None:
    created_ids = {e.id for e in into.entities_created}
    for e in d.entities_created:
        if e.id not in created_ids:
            into.entities_created.append(e)
    into.entities_updated.extend(d.entities_updated)
    into.relations_added.extend(d.relations_added)
    into.relations_closed.extend(d.relations_closed)
    into.evidence_added.extend(d.evidence_added)
    added = {b.id for b in into.beliefs_added}
    for b in d.beliefs_added:
        if b.id not in added:
            into.beliefs_added.append(b)
    for b in d.beliefs_updated:
        if b.id in added:
            into.beliefs_added = [b if x.id == b.id else x for x in into.beliefs_added]
        else:
            into.beliefs_updated.append(b)
    into.events_added.extend(d.events_added)


# =========================================================================================
class ContextPacket(BaseModel):
    objective: str
    relevant_entities: list[dict[str, Any]] = Field(default_factory=list)
    verified_facts: list[str] = Field(default_factory=list)
    contested_beliefs: list[str] = Field(default_factory=list)
    recent_events: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    world_version: int = 0

    def render(self) -> str:
        lines = [f"[world v{self.world_version}]"]
        lines += [f"fact: {f}" for f in self.verified_facts]
        lines += [f"contested: {c}" for c in self.contested_beliefs]
        lines += [f"event: {e}" for e in self.recent_events]
        lines += [f"procedure: {p}" for p in self.procedures]
        return "\n".join(lines) if len(lines) > 1 else ""


class GraphRAG:
    """semantic seed -> graph expansion -> temporal filter -> belief confidence -> rights filter."""

    def __init__(self, world: WorldModel) -> None:
        self.world = world

    def packet(self, objective: str, *, max_visibility: Visibility = Visibility.INTERNAL, depth: int = 1,
               min_confidence: float = 0.6, limit: int = 12, at: str | None = None,
               procedures: list[str] | None = None) -> ContextPacket:
        w = self.world
        q = _tokens(objective)
        allowed = VISIBILITY_RANK[max_visibility]
        seeds = []
        for e in w.entities.values():
            if VISIBILITY_RANK[e.visibility] > allowed or e.entity_type in ("task", "value"):
                continue
            names = _tokens(" ".join([e.canonical_name or "", *e.aliases]))
            overlap = len(q & names)
            if overlap:
                seeds.append((overlap / max(1, len(names)), e))
        seeds.sort(key=lambda x: -x[0])
        seed_ids = [e.id for _, e in seeds[:5]]
        facts, contested, refs = [], [], []
        ids = set(seed_ids)
        for sid in seed_ids:
            ids |= {n["id"] for n in w.neighbors(sid, depth=depth, at=at)["nodes"]}
        now_beliefs: list[Belief] = [b for b in w.beliefs.values()
                                     if VISIBILITY_RANK[b.visibility] <= allowed and b.status != BeliefStatus.OBSOLETE]
        for b in sorted(now_beliefs, key=lambda b: -b.effective_confidence()):
            relevant = (b.subject_id in ids) or len(q & _tokens(b.proposition)) >= max(2, len(q) // 3)
            if not relevant:
                continue
            if b.status == BeliefStatus.CONTESTED:
                contested.append(f"{b.proposition} (conf {b.confidence:.2f})")
            elif b.effective_confidence() >= min_confidence and b.status in (BeliefStatus.SUPPORTED,
                                                                              BeliefStatus.VERIFIED):
                facts.append(f"{b.proposition} [{b.status.value.lower()} {b.confidence:.2f}]")
            refs.extend(b.supporting_evidence[:2])
            if len(facts) + len(contested) >= limit:
                break
        for r in w.current_relations(at=at):
            if r.subject_id in seed_ids and len(facts) < limit and r.predicate not in ("USED_MODEL", "USED_TOOL"):
                s, o = w.entities.get(r.subject_id), w.entities.get(r.object_id)
                if s and o and VISIBILITY_RANK[s.visibility] <= allowed:
                    text = f"{s.canonical_name or s.id} {r.predicate} {o.canonical_name or o.id}"
                    if not any(f.startswith(text) for f in facts):
                        facts.append(text)
        events = [f"{e.started_at[:19]} {e.event_type} {e.properties}" for e in
                  sorted((e for e in w.events.values() if set(e.participants) & set(seed_ids)),
                         key=lambda e: e.started_at)[-5:]]
        return ContextPacket(objective=objective,
                             relevant_entities=[{"id": i, "type": w.entities[i].entity_type} for i in seed_ids],
                             verified_facts=list(dict.fromkeys(facts))[:limit], contested_beliefs=contested[:5],
                             recent_events=events, procedures=procedures or [], source_refs=refs[:20],
                             world_version=w.version)


# =========================================================================================
def code_graph_delta(root: Path, world: WorldModel, repo_name: str | None = None) -> KnowledgeDelta:
    """REPOSITORY -> MODULE -> CLASS/FUNCTION, CALLS, IMPORTS, and TEST COVERS FUNCTION edges."""
    repo = repo_name or root.name
    delta = KnowledgeDelta(source=f"codegraph:{repo}")
    repo_e, _ = world.entity_delta(repo, entity_type="repository", entity_id=f"repo/{repo}", source="codegraph")
    delta.entities_created.append(repo_e)
    functions: dict[str, str] = {}
    calls: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        if any(part.startswith(".") or part in ("__pycache__", "node_modules", ".venv") for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        is_test = path.name.startswith("test_") or "/tests/" in f"/{rel}"
        mod_id = f"module/{repo}/{rel}"
        delta.entities_created.append(world.entity_delta(rel, entity_type="test_module" if is_test else "module",
                                                         entity_id=mod_id, source="codegraph", path=rel)[0])
        delta.relations_added.append(WorldRelation(subject_id=repo_e.id, predicate="CONTAINS", object_id=mod_id,
                                                   confidence=1.0))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for n in names:
                    if n:
                        delta.relations_added.append(WorldRelation(subject_id=mod_id, predicate="IMPORTS",
                                                                   object_id=f"module-name/{n}", confidence=1.0))
        for node in tree.body:
            items = [node] + (list(node.body) if isinstance(node, ast.ClassDef) else [])
            for item in items:
                if isinstance(item, ast.ClassDef):
                    cid = f"class/{repo}/{rel}:{item.name}"
                    delta.entities_created.append(world.entity_delta(item.name, entity_type="class", entity_id=cid,
                                                                     source="codegraph", line=item.lineno)[0])
                    delta.relations_added.append(WorldRelation(subject_id=mod_id, predicate="DEFINES", object_id=cid,
                                                               confidence=1.0))
                    for base in item.bases:
                        if isinstance(base, ast.Name):
                            delta.relations_added.append(WorldRelation(subject_id=cid, predicate="INHERITS",
                                                                       object_id=f"name/{base.id}", confidence=0.9))
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fid = f"function/{repo}/{rel}:{item.name}"
                    kind = "test" if is_test and item.name.startswith("test") else "function"
                    delta.entities_created.append(world.entity_delta(item.name, entity_type=kind, entity_id=fid,
                                                                     source="codegraph", line=item.lineno,
                                                                     args=[a.arg for a in item.args.args])[0])
                    delta.relations_added.append(WorldRelation(subject_id=mod_id, predicate="DEFINES", object_id=fid,
                                                               confidence=1.0))
                    if kind == "function":
                        functions.setdefault(item.name, fid)
                    for sub in ast.walk(item):
                        if isinstance(sub, ast.Call):
                            f = sub.func
                            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                            if name:
                                calls.append((fid, name))
    for caller, name in calls:
        if name in functions and functions[name] != caller:
            pred = "COVERS" if caller.split(":")[-1].startswith("test") else "CALLS"
            delta.relations_added.append(WorldRelation(subject_id=caller, predicate=pred, object_id=functions[name],
                                                       confidence=1.0))
    return delta


def runtime_graph_delta(world: WorldModel, registry, nodes: list[dict] | None = None) -> KnowledgeDelta:
    """SERVICE/NODE/GPU/MODEL topology from the registry and the cluster node registry."""
    delta = KnowledgeDelta(source="runtime")
    for m in registry.all():
        e, _ = world.entity_delta(m.id, entity_type="model", entity_id=f"model/{m.id}", source="registry",
                                  provider=m.provider, local=m.local, tier=m.tier, enabled=m.enabled,
                                  queue_depth=m.queue_depth, load=m.current_load)
        delta.entities_updated.append(e)
        svc = f"service/{m.provider.split(':')[0]}"
        delta.entities_updated.append(world.entity_delta(svc, entity_type="service", entity_id=svc,
                                                         source="registry")[0])
        if not world.current_relations(svc, "SERVES", e.id):
            delta.relations_added.append(WorldRelation(subject_id=svc, predicate="SERVES", object_id=e.id,
                                                       confidence=1.0))
    for n in nodes or []:
        nid = f"node/{n['id']}"
        delta.entities_updated.append(world.entity_delta(n["id"], entity_type="node", entity_id=nid, source="cluster",
                                                         healthy=n.get("healthy", True))[0])
        for g in n.get("gpus", []):
            gid = f"gpu/{n['id']}/{g['id']}"
            delta.entities_updated.append(world.entity_delta(f"{n['id']}:{g['id']}", entity_type="gpu", entity_id=gid,
                                                             source="cluster", model=g.get("model"),
                                                             free_vram_gb=g.get("free_vram_gb"))[0])
            if not world.current_relations(nid, "HAS_GPU", gid):
                delta.relations_added.append(WorldRelation(subject_id=nid, predicate="HAS_GPU", object_id=gid,
                                                           confidence=1.0))
    return delta
