# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Capture Pipeline: the learning plane attached to every completed task.

    CapturePipeline
    ├── WorldCapture       claims/observations -> KnowledgeDelta -> world version
    ├── ArtifactCapture    answer / code / patches -> content-addressed store
    ├── CorpusCapture      one execution -> several candidate examples (gated, quarantined)
    ├── ProvenanceCapture  TASK_EXECUTED in the signed hash-chained ledger
    ├── FlightRecorder     reproducible manifest (code/policy/world/corpus versions, models, hashes)
    └── LearningSnapshot   what HYDRA learned from this task

Every stage is non-fatal: capture never fails a user request. Shadow runs capture nothing.
Ledger and corpus writes that fail inline are deferred to the capture outbox (retry +
dead-letter) instead of being lost."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import hydra
from hydra.core.events import EventType
from hydra.core.hashing import canonical_json, now_iso, sha256_hex

log = logging.getLogger("hydra.capture")


class CapturePipeline:
    def __init__(self, *, world=None, compiler=None, corpus=None, ledger=None, artifacts=None,
                 flight_dir: Path | None = None, capture_policy=None, policy_version: str = "",
                 config_ref=None, registry=None, outbox=None) -> None:
        self.world = world
        self.compiler = compiler
        self.corpus = corpus
        self.ledger = ledger
        self.artifacts = artifacts
        self.flight_dir = flight_dir
        self.capture_policy = capture_policy
        self.policy_version = policy_version
        self.config_ref = config_ref  # callable -> str
        self.registry = registry
        self.outbox = outbox  # CaptureOutbox | None
        if flight_dir is not None:
            flight_dir.mkdir(parents=True, exist_ok=True)

    def _ingest(self, task_id: str, rec, deferred: list[str]):
        try:
            return self.corpus.ingest(rec)[0]
        except Exception:
            if self.outbox is None:
                raise
            self.outbox.defer("capture.corpus", task_id, {"record": rec.model_dump(mode="json")})
            deferred.append(f"corpus:{rec.id}")
            return None

    def _append_ledger(self, task_id: str, payload: dict, options: dict, deferred: list[str]):
        try:
            return self.ledger.append("TASK_EXECUTED", payload, **options)
        except Exception:
            if self.outbox is None:
                raise
            self.outbox.defer("capture.ledger", task_id,
                              {"event_type": "TASK_EXECUTED", "payload": payload, "options": options})
            deferred.append("ledger")
            return None

    def _cost(self, ctx) -> float:
        total = 0.0
        for e in ctx.events:
            if e.type == EventType.MODEL_COMPLETED and self.registry is not None:
                m = self.registry.models.get(e.payload.get("model", ""))
                if m is not None:
                    total += m.estimate_cost(e.payload.get("input_tokens", 0), e.payload.get("output_tokens", 0))
        return round(total, 6)

    async def capture(self, ctx, *, answer: str, artifacts: list, claims: list, provenance: list,
                      confidence: float, verified: bool) -> dict[str, Any]:
        task_id = str(ctx.task_id)
        snap: dict[str, Any] = {"task_id": task_id}
        deferred: list[str] = []
        world_before = getattr(self.world, "version", None)
        models = list(dict.fromkeys(ctx.state.models_used))
        tools = list(dict.fromkeys(ctx.state.tools_used))
        task_type = ctx.route.task_type.value if ctx.route else "chat"
        # --- artifacts -> CAS
        refs = []
        if self.artifacts is not None:
            try:
                for a in artifacts:
                    content = a.content if isinstance(a.content, str) else json.dumps(a.content, ensure_ascii=False,
                                                                                      default=str)
                    if a.type.value == "image" and len(content) > 200_000:
                        continue
                    m = self.artifacts.put(content, media_type=a.mime, artifact_type=a.type.value, task_id=task_id,
                                           created_by=",".join(models) or "hydra",
                                           metadata={"title": a.title, **{k: v for k, v in a.metadata.items()
                                                                          if isinstance(v, (str, int, float, bool))}})
                    a.metadata["uri"] = m.uri
                    a.metadata["sha256"] = m.sha256
                    refs.append(m.uri)
            except Exception:
                log.exception("artifact capture failed")
        snap["artifacts"] = refs
        # --- world model
        if self.world is not None and self.compiler is not None:
            try:
                delta = self.compiler.compile_task(
                    task_id=task_id, objective=ctx.state.objective or "", task_type=task_type,
                    world_state=ctx.world.model_dump(mode="json") if not ctx.world.empty else None,
                    claims=[c.model_dump() for c in claims], provenance=provenance, models=models, tools=tools,
                    artifacts=refs, sensitivity=ctx.sensitivity, verified=verified, confidence=confidence,
                    tool_results=ctx.state.tool_results)
                version = self.world.apply(delta)
                snap["world_version"] = version
                snap["world_delta"] = {"entities": len(delta.entities_created) + len(delta.entities_updated),
                                       "relations": len(delta.relations_added), "beliefs": len(delta.beliefs_added)
                                       + len(delta.beliefs_updated), "evidence": len(delta.evidence_added)}
            except Exception:
                log.exception("world capture failed")
        # --- corpus
        if self.corpus is not None:
            try:
                from hydra.corpus.capture import capture_task

                recs = capture_task(ctx.events, answer=answer, confidence=confidence, verified=verified,
                                    sensitivity=ctx.sensitivity, task_type=task_type, policy=self.capture_policy,
                                    tenant_id=ctx.request.metadata.get("tenant_id"),
                                    world_version=snap.get("world_version"))
                statuses: Counter = Counter()
                ids = []
                for r in recs:
                    rec = self._ingest(task_id, r, deferred)
                    if rec is None:
                        continue
                    statuses[rec.training_status.value] += 1
                    ids.append(rec.id)
                snap["corpus"] = {"candidates": len(recs), "status": dict(statuses), "record_ids": ids}
            except Exception:
                log.exception("corpus capture failed")
        snap["cost"] = self._cost(ctx)
        # --- flight recorder + ledger
        events = [{"seq": i, "type": e.type.value, "source": e.source,
                   "hash": sha256_hex(canonical_json(e.payload))} for i, e in enumerate(ctx.events)]
        manifest = {
            "task": task_id, "trace": ctx.trace_id or task_id, "recorded_at": now_iso(),
            "code_version": hydra.__version__, "policy_version": self.policy_version,
            "config": self.config_ref() if callable(self.config_ref) else self.config_ref,
            "world_version_before": world_before, "world_version_after": snap.get("world_version"),
            "corpus_offset": getattr(self.corpus, "offset", None),
            "models": [{"logical": m, "provider": (self.registry.models[m].provider if self.registry and m in
                                                    self.registry.models else None),
                        "physical": (self.registry.models[m].physical_name if self.registry and m in
                                     self.registry.models else None)} for m in models],
            "tools": tools, "artifacts": refs, "events": events,
            "request_hash": sha256_hex(ctx.request.text), "answer_hash": sha256_hex(answer or ""),
            "confidence": confidence, "verified": verified, "sensitivity": ctx.sensitivity,
        }
        manifest["manifest_hash"] = sha256_hex(canonical_json(manifest))
        if self.flight_dir is not None:
            try:
                (self.flight_dir / f"{task_id}.json").write_text(json.dumps(manifest, indent=2, default=str),
                                                                 encoding="utf-8")
                snap["flight_recorder"] = f"{task_id}.json"
            except OSError:
                log.exception("flight recorder failed")
        if self.ledger is not None:
            try:
                e = self._append_ledger(task_id, {
                    "task": task_id, "task_type": task_type, "models": models, "tools": tools, "artifacts": refs,
                    "manifest_hash": manifest["manifest_hash"], "answer_hash": manifest["answer_hash"],
                    "world_version": snap.get("world_version"), "corpus": snap.get("corpus", {}).get("record_ids", []),
                    "verified": verified, "confidence": confidence},
                    {"object_type": "task", "object_id": task_id, "producer": "kernel",
                     "confidentiality": "CONFIDENTIAL" if ctx.sensitivity >= 2 else "INTERNAL_CONFIDENTIAL"}, deferred)
                if e is not None:
                    snap["ledger_event"] = {"sequence": e.sequence, "hash": e.event_hash}
            except Exception:
                log.exception("ledger capture failed")
        if deferred:
            snap["deferred"] = deferred
        snap["potential_ip"] = None
        return snap

    async def capture_failure(self, ctx, error: str) -> None:
        if self.corpus is not None:
            try:
                from hydra.corpus.capture import capture_task

                for r in capture_task(ctx.events, answer=None, confidence=0.0, verified=False,
                                      sensitivity=ctx.sensitivity,
                                      task_type=ctx.route.task_type.value if ctx.route else "chat",
                                      policy=self.capture_policy):
                    self._ingest(str(ctx.task_id), r, [])
            except Exception:
                log.exception("failure capture failed")
        if self.ledger is not None:
            try:
                self._append_ledger(str(ctx.task_id), {"task": str(ctx.task_id), "failed": True, "error": error[:500]},
                                    {"object_type": "task", "object_id": str(ctx.task_id), "producer": "kernel"}, [])
            except Exception:
                log.exception("ledger failure capture failed")
