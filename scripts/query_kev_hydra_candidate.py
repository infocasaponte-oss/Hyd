# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Demonstrate Kev's typed decision plus HYDRA's actual generated response."""
import asyncio
import argparse
import json
from pathlib import Path

from hydra.core.config import Settings
from hydra.engine import HydraEngine


async def main(version="2", checkpoint=None):
    settings = Settings(models_config=Path(f"config/models.hydra-instruction-v{version}.yaml"), offline=False,
                        data_dir=Path("runtime/kev-hydra-candidate"), capture=False, runtime_monitor=False,
                        budget_time_scale=6, decision_shadow_endpoint="http://127.0.0.1:8009",
                        decision_shadow_timeout_s=5,
                        decision_full_contract=checkpoint is not None,
                        decision_calibrator_path=checkpoint / "router-calibrator.json" if checkpoint else Path("models/kev-router-calibrator-v4.json"),
                        decision_local_model_path=None, decision_authority_evidence_path=None)
    observed = []
    async with await HydraEngine.create(settings) as engine:
        async def event(e):
            if e.type.value == "route.selected":
                observed.append(e.payload.get("observation"))
        await engine.runtime.bus.subscribe(None, event)
        answer = await engine.query("Dame la bienvenida en una frase breve.", local_only=False, use_cache=False)
    result = {"decision": observed, "answer": answer.answer, "meta": answer.meta.model_dump(mode="json"),
              "control_enabled": False, "note": "Kev classifies; HYDRA 1.5B generates the response"}
    name = "kev-hydra-v3-composed-2026-09-30.json" if version == "3" else "kev-hydra-composed-2026-09-30.json"
    (Path("docs/evidence") / name).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["2", "3"], default="2")
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.version, args.checkpoint))
