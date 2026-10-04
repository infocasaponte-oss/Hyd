# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Model-bound calibrated observations; never authorize actions or change routes."""
import hashlib
import json
import time
from pathlib import Path

from hydra.core.contracts import DecisionObservation, HydraRequest
from hydra.router.observer import policy_gate
from hydra.training.calibrator import TemperatureCalibrator
from hydra.training.specialists import TextClassifier


class CalibratedLocalObserver:
    def __init__(self, model_path: Path, manifest_path: Path):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != "hydra-local-routing-calibration/1":
            raise ValueError("invalid local routing calibration")
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != manifest.get("model_sha256"):
            raise ValueError("calibration belongs to a different classifier")
        import hydra.training.specialists as features
        feature_hash = hashlib.sha256(Path(features.__file__).read_bytes()).hexdigest()
        if feature_hash != manifest.get("feature_implementation_sha256"):
            raise ValueError("calibration feature implementation mismatch")
        self.classifier = TextClassifier.load(model_path)
        if sorted(self.classifier.labels) != sorted(manifest.get("labels", [])):
            raise ValueError("calibration labels mismatch")
        self.calibrator = TemperatureCalibrator(manifest["temperature"])
        self.model = f"hydra-local-shadow:{digest[:12]}"

    async def observe(self, request: HydraRequest) -> DecisionObservation:
        start = time.perf_counter()
        gate = policy_gate(request.last_user_text)
        if gate:
            return DecisionObservation(status="observed", model="hydra-policy-v2", reason=gate[1],
                                       selected=gate[0], probabilities={gate[0]: 1}, confidence=1)
        probabilities = self.calibrator.probabilities(self.classifier.predict_proba(request.last_user_text))
        selected = max(probabilities, key=probabilities.get)
        return DecisionObservation(status="observed", model=self.model, reason="calibrated_shadow_only",
                                   selected=selected, probabilities=probabilities,
                                   confidence=probabilities[selected], elapsed_ms=(time.perf_counter()-start)*1000)

    async def close(self):
        pass
