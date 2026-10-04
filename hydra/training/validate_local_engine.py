# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Real facade smoke with artifact identity and a separate Docker verification."""
import asyncio
import json
import re
from pathlib import Path

import httpx

from hydra.core.config import Settings
from hydra.core.contracts import ExecutionMode
from hydra.engine import HydraEngine
from hydra.tools.sandbox import DockerSandbox
from hydra.training.evaluate_corpus import candidate_hash, model_identity, verification_program


async def validate() -> dict:
    expected = candidate_hash(Path("models/hydra-q5/build-manifest.json"))
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=30) as client:
        identity = await model_identity(client, "hydra-q5-candidate", expected)
        settings = Settings(models_config=Path("config/models.hydra-q5.yaml"), offline=False,
                            runtime_monitor=False, capture=False, router_model="", decision_shadow_endpoint="",
                            data_dir=Path("runtime/q5-engine-validation"))
        async with await HydraEngine.create(settings) as engine:
            response = await engine.query(
                "Escribe solo código Python: def solve(xs) devuelve el prefijo común más largo "
                "de las cadenas de xs; lista vacía devuelve cadena vacía.",
                mode=ExecutionMode.FAST, use_cache=False)
        gpu = await client.get("/api/ps")
        gpu.raise_for_status()
        if await model_identity(client, "hydra-q5-candidate", expected) != identity:
            raise ValueError("model changed during validation")
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", response.answer, re.S)
    code = match.group(1) if match else response.answer
    cases = [{"input": [], "expected": ""}, {"input": ["flor", "flota"], "expected": "flo"},
             {"input": ["abc", ""], "expected": ""}]
    program, marker = verification_program(code, cases)
    checked = await DockerSandbox().execute_python(program, timeout=15)
    report = {"model_identity": identity, "response": response.model_dump(mode="json"),
              "ollama_loaded_models": gpu.json(),
              "independent_docker_check": {"passed": checked.exit_code == 0 and marker in checked.stdout.splitlines(),
                                           "stderr": checked.stderr, "cases": len(cases)},
              "approved": False,
              "limitations": "One live engine request; independent check does not alter engine verified status."}
    output = Path("data/evaluations/q5-engine-live.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(validate()), indent=2, ensure_ascii=False))
