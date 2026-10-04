# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.core.config import Settings
from hydra.training.calibrator import TemperatureCalibrator


def test_settings_accepts_external_calibrator(tmp_path):
    path = tmp_path / "calibrator.json"
    TemperatureCalibrator(2).save(path, calibration_dataset_sha256="dataset")
    settings = Settings(decision_calibrator_path=path)
    assert settings.decision_calibrator_path == path


def test_calibrator_rejects_manifest_without_dataset_hash(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"format":"hydra-decision-calibrator/1","temperature":2}', encoding="utf-8")
    with pytest.raises(ValueError):
        TemperatureCalibrator.load(path)
