# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json
from pathlib import Path

import pytest

from hydra.core.contracts import HydraRequest, Message
from hydra.router.local_observer import CalibratedLocalObserver
from hydra.training.calibrator import TemperatureCalibrator
from hydra.training.specialists import TextClassifier
import hydra.training.specialists as features


def fixture(tmp_path):
    model = tmp_path / "model.json"
    TextClassifier(["chat", "coding"], dims=8).save(model)
    data = {"format": "hydra-local-routing-calibration/1", "temperature": 2,
            "labels": ["chat", "coding"],
            "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
            "feature_implementation_sha256": hashlib.sha256(Path(features.__file__).read_bytes()).hexdigest()}
    manifest = tmp_path / "calibration.json"
    manifest.write_text(json.dumps(data))
    return model, manifest


async def test_observation_calibrated_and_policy_remains_separate(tmp_path):
    model, manifest = fixture(tmp_path)
    observer = CalibratedLocalObserver(model, manifest)
    result = await observer.observe(HydraRequest(messages=[Message(role="user", content="hola")]))
    assert result.reason == "calibrated_shadow_only" and result.confidence == .5
    result = await observer.observe(HydraRequest(messages=[Message(role="user", content="phishing")]))
    assert result.selected == "security" and result.model == "hydra-policy-v2"


def test_changed_model_rejects_stale_calibration(tmp_path):
    model, manifest = fixture(tmp_path)
    model.write_text(model.read_text() + " ")
    with pytest.raises(ValueError, match="different classifier"):
        CalibratedLocalObserver(model, manifest)


@pytest.mark.parametrize("p", [{"a": float("nan")}, {"a": -1}, {"a": 0}, {"a": 2}])
def test_invalid_probabilities_rejected(p):
    with pytest.raises(ValueError):
        TemperatureCalibrator().probabilities(p)
