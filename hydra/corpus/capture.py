# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Corpus capture: ONE execution becomes several typed candidate examples.

    answer / routing / tool-use / code-debug / critic / preference / plan /
    failure / contrastive / process-supervision

Everything is derived from the task's event log (so it also works on replays) and enters
the corpus quarantined; the curator decides what becomes trainable."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from hydra.blackboard.projector import replay
from hydra.core.events import EventType, HydraEvent
from hydra.corpus.gates import QualityInputs, quality_score
from hydra.corpus.records import Classification, CorpusRecord, RecordType, RightsMetadata
from hydra.language import detect_language
from hydra.verification.consensus import pair_agreement

CODE = re.compile(r"```(\w*)\s*\n(.*?)```", re.S)


class CapturePolicy(BaseModel):
    auto_training_max_sensitivity: int = 0
    """Our own executions at or below this sensitivity are trainable by default (0 = PUBLIC)."""
    min_confidence: float = 0.0
    capture_failures: bool = True
    owner: str = "Luis Manuel Cousido Hermida"


def _classification(sensitivity: int) -> Classification:
    return [Classification.PUBLIC, Classification.INTERNAL, Classification.CONFIDENTIAL,
            Classification.TRADE_SECRET][max(0, min(3, sensitivity))]


def capture_task(events: list[HydraEvent], *, answer: str | None, confidence: float, verified: bool,
                 sensitivity: int, task_type: str, policy: CapturePolicy | None = None,
                 tenant_id: str | None = None, world_version: int | None = None) -> list[CorpusRecord]:
    policy = policy or CapturePolicy()
    if not events:
        return []
    task_id = str(events[0].task_id)
    st = replay(events)
    objective = st.objective or ""
    route = next((e.payload for e in events if e.type == EventType.ROUTE_SELECTED), {})
    verification = st.verification or {}
    v_score = float(verification.get("score", confidence if verified else 0.0) or 0.0)
    models = [e.payload.get("model") for e in events if e.type == EventType.MODEL_COMPLETED]
    evidence_strength = 0.0
    if st.provenance:
        strengths = [max((s.get("strength", 0) for s in p.get("sources", [])), default=0) for p in st.provenance]
        evidence_strength = sum(strengths) / len(strengths)
    tool_ok = [r for r in st.tool_results if r.get("success")]
    language = detect_language(objective) if objective else None
    trainable = sensitivity <= policy.auto_training_max_sensitivity
    base_rights = RightsMetadata(owner=policy.owner, license="proprietary", training_allowed=trainable,
                                 redistribution_allowed=False, cloud_allowed=sensitivity == 0)
    prov = {"origin": "hydra_execution", "task_id": task_id, "models": sorted({m for m in models if m}),
            "tools": sorted({r.get("tool") for r in st.tool_results}),
            "verified_by": [x for x, ok in (("tools", bool(tool_ok)), ("critic", bool(st.critiques)),
                                            ("verifier", verified)) if ok], "world_version": world_version}
    domain = [task_type]
    cls = _classification(sensitivity)
    failed = any(e.type == EventType.TASK_FAILED for e in events)

    def rec(rtype: RecordType, *, quality_inputs: QualityInputs | None = None, verification_score: float | None = None,
            capabilities: list[str] | None = None, **fields: Any) -> CorpusRecord:
        qi = quality_inputs or QualityInputs(verification=v_score, evidence=evidence_strength,
                                             correctness=confidence if verified else confidence * 0.6)
        return CorpusRecord(record_type=rtype, source_task_id=task_id, source_id=task_id, language=language,
                            quality=quality_score(qi), verification=verification_score if verification_score
                            is not None else v_score, domain=domain, capabilities=capabilities or [task_type],
                            classification=cls, tenant_id=tenant_id, provenance=dict(prov),
                            rights=base_rights.model_copy(), **fields)

    out: list[CorpusRecord] = []
    if answer and not failed and confidence >= policy.min_confidence:
        out.append(rec(RecordType.SFT, input={"prompt": objective},
                       output={"answer": answer, "messages": [{"role": "user", "content": objective},
                                                              {"role": "assistant", "content": answer}]},
                       metadata={"confidence": confidence, "verified": verified}))
    if route:
        out.append(rec(RecordType.ROUTING_DECISION, input={"query": objective},
                       output={k: route.get(k) for k in ("task_type", "complexity", "risk", "requires_tools",
                                                         "requires_vision", "requires_reasoning",
                                                         "requires_verification", "requires_memory")},
                       capabilities=["routing"],
                       metadata={"arm": route.get("arm"), "outcome_confidence": confidence}))
    tools_available = sorted({r.get("tool") for r in st.tool_results})
    for r in tool_ok[:5]:
        out.append(rec(RecordType.TOOL_USE, input={"prompt": objective, "available_tools": tools_available},
                       action={"name": r.get("tool"), "arguments": r.get("arguments")},
                       output={"tool_result": str(r.get("result"))[:4000], "final_answer": (answer or "")[:4000]},
                       capabilities=["tool_use.selection", "tool_use.argument_generation"],
                       metadata={"duration_ms": r.get("duration_ms"), "deterministic_proof": True}))
    if task_type == "coding" and answer:
        before = [m.group(2) for m in CODE.finditer(objective)]
        after = [m.group(2) for m in CODE.finditer(answer)]
        tests = [{"tool": r.get("tool"), "exit_code": (r.get("result") or {}).get("exit_code")
                  if isinstance(r.get("result"), dict) else None} for r in st.tool_results]
        if before or after:
            passed = any(t["exit_code"] == 0 for t in tests)
            out.append(rec(RecordType.CODE_DEBUG, input={"problem": objective, "before": "\n".join(before)[:8000]},
                           output={"patch": "\n".join(after)[:8000], "explanation": answer[:4000]},
                           content={"tests": {"after": "PASS" if passed else ("FAIL" if tests else "NOT_RUN")},
                                    "tool_runs": tests},
                           capabilities=["coding.debugging", "coding.python"],
                           metadata={"deterministic_proof": passed}))
    for c in st.critiques[:3]:
        cand = next((x for x in st.candidates if x.get("claim_id") == c.get("target")), {})
        out.append(rec(RecordType.CRITIC, input={"candidate": str(cand.get("answer", ""))[:4000],
                                                 "evidence": [str(r.get("result"))[:500] for r in tool_ok[:3]]},
                       output={"verdict": c.get("verdict"), "score": c.get("score"), "errors": c.get("issues", [])},
                       capabilities=["critic"]))
    if answer and len(st.candidates) >= 2:
        chosen_q = v_score
        scored = sorted(((pair_agreement(x.get("answer", ""), answer) * v_score, x) for x in st.candidates
                         if x.get("answer") and x.get("answer") != answer), key=lambda t: t[0])
        if scored:
            rq, rejected = scored[0]
            if chosen_q >= 0.85 and rq <= 0.65 and chosen_q - rq >= 0.15:
                out.append(rec(RecordType.PREFERENCE, input={"prompt": objective},
                               output={"chosen": answer, "rejected": rejected.get("answer")},
                               content={"chosen_quality": round(chosen_q, 3), "rejected_quality": round(rq, 3),
                                        "rejected_model": rejected.get("model")},
                               capabilities=["preference"]))
    plans = [d for d in st.decisions if d.get("type") in (EventType.PLAN_CREATED.value, EventType.PLAN_REVISED.value)]
    if plans:
        steps = plans[-1].get("steps", [])
        out.append(rec(RecordType.PLAN, state={"route": {k: route.get(k) for k in ("task_type", "complexity")},
                                               "memories": len(st.memories)},
                       action={"strategy": plans[-1].get("strategy"),
                               "steps": [s.get("worker") for s in steps if isinstance(s, dict)]},
                       output={"verified": verified, "confidence": confidence, "replans": len(plans) - 1},
                       reward=round(confidence if verified else confidence - 0.3, 3), capabilities=["planning"],
                       input={"objective": objective}))
    escalations = [d for d in st.decisions if d.get("type") == EventType.ESCALATED.value]
    if escalations and answer:
        first = st.candidates[0] if st.candidates else {}
        out.append(rec(RecordType.CONTRASTIVE, input={"task": objective},
                       content={"negative": {"model": escalations[0].get("from"), "answer": first.get("answer", "")[:3000],
                                             "confidence": escalations[0].get("confidence")},
                                "positive": {"answer": answer[:3000], "confidence": confidence}},
                       capabilities=["planning", "routing"], flags=["hard"]))
    failures = [f for f in st.failures if f.get("type") in ("model.failed", "tool.failed")]
    if policy.capture_failures and (failed or failures):
        out.append(rec(RecordType.FAILURE, input={"problem": objective},
                       content={"failures": [{k: f.get(k) for k in ("type", "model", "tool", "error", "kind")}
                                             for f in failures[:5]],
                                "corrected_strategy": [d.get("strategy") for d in plans[1:] if d.get("strategy")],
                                "recovered": not failed},
                       capabilities=["recovery"], flags=["hard"] if not failed else ["frontier"],
                       quality_inputs=QualityInputs(verification=0.9, evidence=0.9, correctness=0.9),
                       verification_score=0.95))
    if len(st.tool_results) >= 2:
        out.append(rec(RecordType.PROCESS_SUPERVISION, input={"prompt": objective},
                       content={"steps": [f"{r.get('tool')}({str(r.get('arguments'))[:120]})" for r in st.tool_results],
                                "labels": [bool(r.get("success")) for r in st.tool_results]},
                       capabilities=["planning.multi_tool"]))
    if escalations or failures or (st.verification or {}).get("passed") is False:
        for r in out:
            if "hard" not in r.flags and r.record_type in (RecordType.SFT, RecordType.CODE_DEBUG):
                r.flags.append("hard")
    return out
