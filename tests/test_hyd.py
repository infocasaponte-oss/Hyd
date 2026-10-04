# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient

from hydra.core.contracts import HydraRequest, Message, DecisionObservation, TaskType
from hydra.hyd.api import register
from hydra.hyd.controller import HydController
from hydra.hyd.engine import HydEngine
from hydra.hyd.model import CandidateRanker
from hydra.router.decision_contract import CRITERIA
from hydra.router.router import CognitiveRouter

ROOT = Path(__file__).resolve().parents[1]


def controller():
    return HydController(ROOT / "config/hyd/model.json", ROOT / "config/hyd/calibration.json")


async def test_cpu_capacity_is_bounded_and_shutdown_closes_all_workers():
    from hydra.hyd.controller import HydBusyError
    hyd = controller()
    finish = threading.Event()
    class BlockingEngine:
        def decide(self, *args):
            finish.wait(3)
            return {"done": True}
    hyd.engine = BlockingEngine()
    tasks = [asyncio.create_task(hyd.decide("", {})) for _ in range(hyd._capacity)]
    try:
        await asyncio.sleep(0)
        assert hyd._capacity == 4
        with pytest.raises(HydBusyError):
            await hyd.decide("", {})
        finish.set()
        assert all(result == {"done": True} for result in await asyncio.gather(*tasks))
        await hyd.close()
        with pytest.raises(HydBusyError, match="closed"):
            await hyd.decide("", {})
    finally:
        finish.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await hyd.close()


def test_real_model_isolation_permutation_and_revision():
    hyd = controller()
    question = {"type": "choice", "criteria": CRITERIA}
    state = "Escribe una función Python que sume dos números."
    alone = hyd.engine.decide(state, {"task": question})["answers"]["task"]
    reversed_question = {"type": "choice", "criteria": dict(reversed(list(CRITERIA.items())))}
    together = hyd.engine.decide(state, {"noise": {"type": "noul"}, "task": reversed_question})
    assert alone == together["answers"]["task"]
    assert alone["choice"] == "coding"
    assert len(together["model_revision"]) == 64
    assert together["generation_tokens"] == 0


def test_unknown_domains_abstain_even_if_model_is_certain():
    hyd = controller()
    for question in ({"type": "choice", "criteria": {"a": "A"}}, {"type": "noul"},
                     {"type": "score", "criteria": ["low", "medium", "high"]}):
        answer = hyd.engine.decide("Some state", {"q": question})["answers"]["q"]
        assert answer["abstained"] and answer["reason"] == "unsupported_domain"
        assert sum(answer["probabilities"].values()) == pytest.approx(1)
        if question["type"] == "score":
            assert answer["score"] == pytest.approx(sum(int(i)*p for i, p in answer["probabilities"].items()))


@pytest.mark.parametrize("questions", [{}, {"x": {"type": "unknown"}},
    {"x": {"type": "score", "criteria": []}}, {"x": {"type": "choice", "criteria": {str(i): "" for i in range(256)}}},
    {"x": {"type": "noul", "criteria": {"invalid": "x"}}}])
def test_contract_failures(questions):
    with pytest.raises(ValueError):
        controller().engine.decide("state", questions)


def test_limits_and_nonfinite_inputs():
    hyd = controller()
    for state in ("x" * 50001, {"bad": float("nan")}):
        with pytest.raises(ValueError):
            hyd.engine.decide(state, {"x": {"type": "noul"}})


def test_model_mutation_invalidates_calibration(tmp_path):
    payload = json.loads((ROOT / "config/hyd/model.json").read_text())
    payload["bias"][0] += .1
    model = tmp_path / "model.json"
    model.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="calibration"):
        HydController(model, ROOT / "config/hyd/calibration.json")


def test_invalid_weights_are_rejected(tmp_path):
    ranker = CandidateRanker(16, 16)
    ranker.save(tmp_path / "model.json")
    data = json.loads((tmp_path / "model.json").read_text())
    data["weights"][0][0] = float("nan")
    (tmp_path / "model.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="parameters"):
        CandidateRanker.load(tmp_path / "model.json")


async def test_private_requests_are_local_and_critical_actions_never_authorized():
    hyd = controller()
    observation = await hyd.observe(HydraRequest(messages=[Message(role="user", content="Escribe código Python")],
                                                local_only=True))
    assert observation.model == "hyd-latest"
    assert hyd.task_hint(observation) is None
    for label in ("tool_use", "security", "privacy", "high_risk_review", "abstain"):
        assert hyd.task_hint(DecisionObservation(status="observed", model=hyd.model, selected=label, confidence=1)) is None
    gated = await hyd.observe(HydraRequest(messages=[Message(role="user", content="drop table production")]))
    assert gated.reason.startswith("policy_gate")


async def test_routing_falls_back_without_promotion():
    hyd = controller()
    router = CognitiveRouter(observer=hyd, authority=hyd)
    request = HydraRequest(messages=[Message(role="user", content="python función suma")])
    decision = await router.route(request)
    assert decision.task_type == TaskType.CODING
    assert decision.observation.model == "hyd-latest"
    assert "decision.controlled_hint" not in decision.signals


def test_api_contract_and_authentication():
    app = FastAPI()
    hyd = controller()
    app.state.runtime = SimpleNamespace(kernel=SimpleNamespace(router=SimpleNamespace(observer=hyd)))
    async def auth():
        return True
    register(app, [Depends(auth)])
    client = TestClient(app)
    response = client.post("/v1/systemone", json={"state": "Python code", "questions": {
        "task": {"type": "choice", "criteria": CRITERIA}}})
    assert response.status_code == 200 and response.headers["x-typesafe-request-id"]
    assert client.get("/v1/hyd/status").json()["authority_enabled"] is False
    batch = {"state": "Python code", "questions": {"task": {"type": "choice", "criteria": CRITERIA},
        "other": {"type": "noul"}}}
    full = client.post("/v1/systemone", json=batch).json()
    separated = client.post("/v1/systemone/separate", json=batch)
    assert separated.status_code == 200 and separated.json()["answers"] == full["answers"]
    permuted = client.post("/v1/systemone/permute", json={"request": batch, "question": "task", "n_perm": 3})
    assert permuted.status_code == 200 and permuted.json()["argmax_stable"]
    assert max(permuted.json()["spread"].values()) == 0
    assert client.post("/v1/systemone", json={"model": "kev-latest", "state": "", "questions": {
        "x": {"type": "noul"}}}).status_code == 422
    async def denied():
        raise HTTPException(401)
    app.dependency_overrides[auth] = denied
    assert client.get("/v1/hyd/status").status_code == 401


def test_ties_use_stable_identifiers():
    engine = HydEngine(CandidateRanker(16, 16))
    assert engine.decide("", {"q": {"type": "choice", "criteria": {"z": "", "a": ""}}})["answers"]["q"]["choice"] == "a"
    assert np.isfinite(engine.ranker.weights).all()


async def test_default_bootstrap_replaces_external_sidecar(runtime):
    assert isinstance(runtime.kernel.router.observer, HydController)
    assert runtime.kernel.router.authority is runtime.kernel.router.observer


def test_typed_training_and_family_leakage(tmp_path):
    from hydra.hyd.train_typed import train
    question = {"type": "noul", "criteria": {"false": "cold", "true": "hot"}}
    def record(text, split, family, target):
        return {"state": text, "question": question, "target": target,
                "split": split, "family": family, "training_allowed": split == "train",
                "rights": {"verified": True, "license": "proprietary-hydra-authored"}}
    train_file, cal_file = tmp_path / "train.jsonl", tmp_path / "cal.jsonl"
    training = [record("boiling hot", "train", "training", {"false": 0, "true": 1}),
                record("freezing cold", "train", "training", {"false": 1, "true": 0})]
    calibration = record("warm hot", "calibration", "heldout", {"false": 0, "true": 1})
    train_file.write_text("\n".join(json.dumps(r) for r in training))
    cal_file.write_text(json.dumps(calibration))
    report = train(train_file, cal_file, tmp_path / "typed", epochs=2)
    assert report["status"] == "REQUIRES_INDEPENDENT_EVALUATION"
    hyd = HydController(tmp_path / "typed/model.json", tmp_path / "typed/calibration.json")
    answer = hyd.engine.decide("warm hot", {"q": question})["answers"]["q"]
    assert answer["reason"] != "unsupported_domain"
    calibration["family"] = "training"
    cal_file.write_text(json.dumps(calibration))
    with pytest.raises(ValueError, match="families overlap"):
        train(train_file, cal_file, tmp_path / "refused", epochs=2)


def test_standalone_service_discovery_and_auth(tmp_path):
    from hydra.core.config import Settings
    from hydra.hyd.serve import create_app
    app = create_app(Settings(_env_file=None, api_key="hyd-test-key", client_keys_file=tmp_path / "keys.json"))
    client = TestClient(app)
    assert client.get("/v1/models").status_code == 401
    response = client.get("/v1/models", headers={"Authorization": "Bearer hyd-test-key"})
    assert response.status_code == 200
    assert response.json()["models"][0]["name"] == "hyd-latest"
