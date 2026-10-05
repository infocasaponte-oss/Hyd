# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Opt-in controller for new heads, preserving the legacy runtime/calibration digest."""
import hashlib
import json

from hydra.hyd.continual import ContinualRanker, code_digest
from hydra.hyd.controller import HydController, implementation_digest
from hydra.hyd.engine import HydEngine
from hydra.router.decision_authority import DecisionAuthority
from hydra.router.decision_contract import CRITERIA


class ContinualController(HydController):
    def __init__(self, model_path, calibration_path, evidence_path=None, fallback=None):
        ranker = ContinualRanker.load(model_path)
        raw = calibration_path.read_bytes()
        calibration = json.loads(raw)
        portable_shadow = (evidence_path is None and calibration.get("status") == "SHADOW_ONLY"
                           and calibration.get("independent_test") is False
                           and calibration.get("portable_routing_code_sha256") == code_digest())
        if (calibration.get("format") != "hyd-calibration/1" or calibration.get("model_sha256") != ranker.revision
                or calibration.get("temperature") != ranker.temperature or calibration.get("criteria") != CRITERIA
                or not calibration.get("dataset_sha256") or
                (calibration.get("implementation_sha256") != implementation_digest() and not portable_shadow)):
            raise ValueError("continuous calibration/model/runtime mismatch")
        self.engine = HydEngine(ranker, calibration["min_confidence"], calibration["min_margin"])
        self.authority = DecisionAuthority(False, self.model)
        self.calibration_revision = hashlib.sha256(raw).hexdigest()
        self._active, self._jobs, self._closed = None, set(), False
        self._capacity = 1 if ranker.exclusive else 4
        self.fallback, self._primary_down_until = fallback, 0
        if evidence_path is not None:
            evidence = json.loads(evidence_path.read_text())
            bound = (evidence.get("format") == "hyd-authority/1" and evidence.get("model_revision") == ranker.revision
                     and evidence.get("implementation_sha256") == implementation_digest()
                     and evidence.get("calibration_sha256") == self.calibration_revision
                     and evidence.get("threshold") == self.engine.min_confidence
                     and evidence.get("margin") == self.engine.min_margin)
            if not bound:
                raise ValueError("authority evidence mismatch")
            self.authority = DecisionAuthority.from_evidence(evidence, self.model)


def controller_class(path):
    return ContinualController if json.loads(path.read_text(encoding="utf-8")).get("format") == "hyd-continual-routing/1" else HydController
