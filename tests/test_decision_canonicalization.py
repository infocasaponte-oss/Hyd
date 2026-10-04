# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import httpx
import pytest

from hydra.providers.decision import LocalSystemOneProvider
from hydra.training.calibrator import TemperatureCalibrator, fit_temperature


def test_choice_wire_order_is_canonical_and_answer_restored():
    seen = []
    def handler(request):
        payload = httpx.Request("POST", "http://local", content=request.content)
        seen.append(payload)
        return httpx.Response(200, json={"model": "test", "answers": {"q": {
            "type": "choice", "choice": "a", "confidence": 0.5,
            "probabilities": {"a": 0.5, "z": 0.5}}}})
    # use a response whose labels match canonical sorted order, while caller order is z,a
    provider = LocalSystemOneProvider(model="test", transport=httpx.MockTransport(handler))
    async def run():
        return await provider.decide("x", {"q": {"type": "choice", "criteria": {"z": "Z", "a": "A"}}})
    import asyncio
    result = asyncio.run(run())
    assert list(result["answers"]["q"]["probabilities"]) == ["z", "a"]
    assert list(__import__("json").loads(seen[0].content)["questions"]["q"]["criteria"]) == ["a", "z"]


def test_temperature_calibration_softens_and_roundtrips(tmp_path):
    calibrator = TemperatureCalibrator(2)
    answer = calibrator.apply({"choice": "a", "probabilities": {"a": .99, "b": .01}})
    assert answer["probabilities"]["a"] < .99
    path = tmp_path / "calibrator.json"
    calibrator.save(path, calibration_dataset_sha256="abc")
    assert TemperatureCalibrator.load(path).temperature == 2


def test_fit_temperature_uses_only_rows_with_labels():
    rows = [{"expected": "a", "probabilities": {"a": .99, "b": .01}},
            {"expected": "b", "probabilities": {"a": .99, "b": .01}}]
    assert fit_temperature(rows) > 1


@pytest.mark.parametrize("temperature", [0, -1, float("nan")])
def test_calibrator_rejects_invalid_temperature(temperature):
    with pytest.raises(ValueError):
        TemperatureCalibrator(temperature)
