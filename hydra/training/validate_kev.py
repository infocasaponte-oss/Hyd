# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Fail-closed live Kev smoke; requires a pinned checkpoint served on CUDA."""
import asyncio
import json
import time
from pathlib import Path

from hydra.providers.decision import LocalSystemOneProvider

PIN = "jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e"
CASES = [("El paquete llegó roto. Solicito un reembolso.", "refund"),
         ("No puedo iniciar sesión, aparece un error de contraseña.", "technical"),
         ("¿Cuánto cuesta el plan anual?", "pricing")]


async def validate(output: Path = Path("data/evaluations/kev-live.json")) -> dict:
    report = {"status": "NOT_VALIDATED", "approved": False, "cases": [],
              "limitations": "Three classification smoke cases, not calibration or tool-routing validation."}
    provider = LocalSystemOneProvider(timeout=60)
    try:
        response = await provider.client.get("/v1/models", timeout=5)
        response.raise_for_status()
        cards = response.json()["models"]
        card = next(c for c in cards if c["name"] == provider.model)
        report["server"] = card
        if card.get("run") != PIN or not card.get("device", "").startswith("cuda"):
            raise ValueError("server must report the pinned checkpoint on CUDA")
        questions = {"topic": {"type": "choice", "criteria": {
            "refund": "Solicitud de devolución o reembolso",
            "technical": "Incidencia técnica de acceso",
            "pricing": "Consulta de precios"}}}
        for state, expected in CASES:
            start = time.perf_counter()
            answer = await provider.decide(state, questions)
            report["cases"].append({"expected": expected, "answer": answer,
                                    "latency_ms": (time.perf_counter()-start)*1000,
                                    "passed": answer["answers"]["topic"]["choice"] == expected})
        report["status"] = "INFERENCE_COMPLETED"
        report["correct"] = sum(c["passed"] for c in report["cases"])
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        await provider.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = asyncio.run(validate())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "INFERENCE_COMPLETED" else 1)
