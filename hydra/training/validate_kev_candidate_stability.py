# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Repeated ten-label CUDA inference; stable predictions need not be correct."""
import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.decision_contract import CRITERIA


async def validate(run: Path, output: Path):
    provider = LocalSystemOneProvider(timeout=30)
    chosen = {}
    for row in map(json.loads, Path("data/human-paraphrase-v1.jsonl").read_text(encoding="utf-8").splitlines()):
        chosen.setdefault(row["expected"], row)
    if set(chosen) != set(CRITERIA):
        raise ValueError("Missing decision categories")
    report = {"approved": False, "scope": "Known regression inputs, stability only", "cases": []}
    async def card():
        response = await provider.client.get("/v1/models")
        response.raise_for_status()
        value = next(c for c in response.json()["models"] if c["name"] == provider.model)
        if value["run"] != str(run.resolve()) or value["device"] != "cuda":
            raise ValueError("Wrong checkpoint or execution device")
        return value
    try:
        report["identity"] = await card()
        for label, row in chosen.items():
            repeats = []
            for _ in range(3):
                started = time.perf_counter()
                result = await provider.decide(row["text"], {"task": {"type": "choice", "criteria": CRITERIA}})
                answer = result["answers"]["task"]
                repeats.append({"choice": answer["choice"], "probabilities": answer["probabilities"],
                                "latency_ms": (time.perf_counter()-started)*1000})
            keys = repeats[0]["probabilities"]
            drift = max(abs(r["probabilities"][k]-repeats[0]["probabilities"][k]) for r in repeats for k in keys)
            report["cases"].append({"id": row["id"], "expected": label, "repeats": repeats,
                "stable_choice": len({r["choice"] for r in repeats}) == 1, "max_probability_drift": drift})
        report["final_identity"] = await card()
        latencies = [r["latency_ms"] for c in report["cases"] for r in c["repeats"]]
        report.update(complete=True, calls=len(latencies), stable_cases=sum(c["stable_choice"] for c in report["cases"]),
                      cases_count=len(chosen), median_latency_ms=statistics.median(latencies),
                      max_latency_ms=max(latencies), max_probability_drift=max(c["max_probability_drift"] for c in report["cases"]))
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("cases", "identity", "final_identity")}, indent=2))
    finally:
        await provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(validate(args.run, args.output))
