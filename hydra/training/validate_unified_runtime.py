# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Run the configured HYDRA facade with Q5 generation and calibrated Kev shadow."""
import asyncio
import json
from pathlib import Path

from hydra.core.config import Settings
from hydra.core.contracts import ExecutionMode
from hydra.engine import HydraEngine


async def validate() -> dict:
    settings = Settings(models_config=Path("config/models.hydra-local.yaml"), offline=False,
                        runtime_monitor=False, capture=False, router_model="",
                        decision_shadow_endpoint="http://127.0.0.1:8009",
                        decision_shadow_timeout_s=2.0,
                        decision_calibrator_path=Path("models/kev-calibrator-v3.json"),
                        data_dir=Path("runtime/unified-runtime-validation"))
    async with await HydraEngine.create(settings) as engine:
        response = await engine.query(
            "Explica brevemente qué es una función pura en Python.",
            mode=ExecutionMode.BALANCED, local_only=True, use_cache=False)
    report = {"response": response.model_dump(mode="json"), "configured_model": "hydra-q5-candidate",
              "decision_calibrator": str(settings.decision_calibrator_path), "approved": False,
              "limitations": "Single live request; Kev remains shadow evidence and does not control routing."}
    output = Path("data/evaluations/unified-runtime-live.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(validate()), indent=2, ensure_ascii=False))
