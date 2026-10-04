# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Real CUDA calibration pilot plus bounded repeated/concurrent stability exercise."""
import asyncio
import json
import math
import time
from pathlib import Path

from hydra.core.contracts import HydraRequest, Message
from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.router import CognitiveRouter
from hydra.training.decision_benchmark import cases, identity, questions
from hydra.training.decision_metrics import metrics, select_threshold
from hydra.training.validate_kev import PIN


async def gpu_snapshot() -> dict:
    try:
        process = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(process.communicate(), 10)
        return {"all_processes_gpu_mib_total_temperature": stdout.decode().strip(), "returncode": process.returncode}
    except Exception as exc:
        return {"error": type(exc).__name__}


async def evaluate(output: Path = Path("data/evaluations/kev-calibration-stability.json")) -> dict:
    start = time.perf_counter()
    report = {"status": "RUNNING", "approved": False, "dataset_sha256": identity(),
              "dataset": cases(), "training_allowed": False, "rows": [], "stability": [],
              "protocol": {"calibration": 24, "test": 24, "ood": 8, "repeat_requests": 120,
                           "stability_min_duration_s": 120,
                           "concurrency": 2, "target_latency_ms": 500, "min_independent_test": 200,
                           "selective_accuracy_target": 0.95, "min_coverage": 0.5,
                           "confidence_metric": "max class probability, not Kev confidence"},
              "limitations": "Authored text-only pilot; repeated prompts are not independent samples. No 24h soak."}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temp = output.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(output)

    provider = LocalSystemOneProvider(timeout=30)
    router = CognitiveRouter()

    async def card():
        result = await provider.client.get("/v1/models", timeout=5)
        result.raise_for_status()
        found = next(c for c in result.json()["models"] if c["name"] == provider.model)
        if found.get("run") != PIN or not found.get("device", "").startswith("cuda"):
            raise ValueError("wrong checkpoint or non-CUDA server")
        return found

    async def infer(row, reverse=False):
        began = time.perf_counter()
        result = {"id": row["id"], "split": row["split"], "expected": row["expected"],
                  "reversed_options": reverse}
        try:
            payload = await asyncio.wait_for(provider.decide(row["text"], questions(reverse)), 30)
            answer = payload["answers"]["task"]
            result.update(selected=answer["choice"], probabilities=answer["probabilities"],
                          reported_confidence=answer["confidence"])
        except Exception as exc:
            result["error"] = type(exc).__name__
        result["latency_ms"] = (time.perf_counter()-began)*1000
        return result

    try:
        report["server_before"] = await card()
        report["gpu_before"] = await gpu_snapshot()
        save()
        for row in cases():
            result = await infer(row)
            baseline = await router.route(HydraRequest(messages=[Message(role="user", content=row["text"])]))
            result["rules_selected"] = baseline.task_type.value
            report["rows"].append(result)
            save()
        calibration = [r for r in report["rows"] if r["split"] == "calibration"]
        test = [r for r in report["rows"] if r["split"] == "test"]
        threshold = select_threshold(calibration)
        report.update(threshold=threshold, calibration=metrics(calibration), test=metrics(test),
                      selective_test=metrics(test, threshold),
                      rules_test_accuracy=sum(r["rules_selected"] == r["expected"] for r in test)/len(test))
        ood = [r for r in report["rows"] if r["split"] == "ood"]
        report["ood_accepted"] = sum(bool(r.get("probabilities")) and
                                     max(r["probabilities"].values()) >= threshold for r in ood)
        report["gpu_after_unique"] = await gpu_snapshot()
        # Same six test cases, balanced across labels; alternating option order.
        repeated = [r for r in cases() if r["split"] == "test" and r["id"].endswith("-4")]
        report["gpu_samples"] = []
        stability_start = time.perf_counter()
        for cycle in range(20):
            for offset in range(0, len(repeated), 2):
                batch = await asyncio.gather(*(infer(row, reverse=bool(cycle % 2)) for row in repeated[offset:offset+2]))
                for result in batch:
                    result["cycle"] = cycle
                    original = next(r for r in test if r["id"] == result["id"])
                    result["agrees_with_original"] = result.get("selected") is not None and result.get("selected") == original.get("selected")
                report["stability"].extend(batch)
                save()
            report["gpu_samples"].append({"cycle": cycle, **await gpu_snapshot()})
            # Spread the exercise across two minutes rather than a single warm burst.
            await asyncio.sleep(max(0, stability_start + (cycle+1)*6 - time.perf_counter()))
        report["stability_elapsed_s"] = time.perf_counter()-stability_start
        report["server_after"] = await card()
        report["gpu_after"] = await gpu_snapshot()
        all_rows = report["rows"] + report["stability"]
        latencies = sorted(r["latency_ms"] for r in all_rows)
        report["summary"] = {"requests": len(all_rows), "errors": sum("error" in r for r in all_rows),
                             "latency_p50_ms": latencies[math.ceil(len(latencies)*0.5)-1],
                             "latency_p95_ms": latencies[math.ceil(len(latencies)*0.95)-1],
                             "over_500ms": sum(t > 500 for t in latencies),
                             "repeat_agreement": sum(r["agrees_with_original"] for r in report["stability"])/120}
        reasons = []
        if len(test) < 200:
            reasons.append("insufficient_independent_test_cases")
        if report["selective_test"]["accuracy_wilson_lower_95"] < 0.9:
            reasons.append("selective_accuracy_lower_bound_below_0.9")
        if report["selective_test"]["coverage"] < 0.5:
            reasons.append("coverage_below_0.5")
        if report["ood_accepted"]:
            reasons.append("ambiguous_or_out_of_scope_accepted")
        if report["summary"]["errors"]:
            reasons.append("request_errors")
        if report["summary"]["latency_p95_ms"] > 500:
            reasons.append("p95_exceeds_observer_budget")
        if report["summary"]["repeat_agreement"] < 0.99:
            reasons.append("repeat_or_option_order_instability")
        reasons.append("sustained_24h_stability_not_tested")
        report.update(status="EVALUATED_PILOT", control_decision="KEEP_SHADOW", blocking_reasons=reasons)
    except Exception as exc:
        report.update(status="FAILED", error=type(exc).__name__ + ": " + str(exc))
    finally:
        await provider.close()
        report["elapsed_s"] = time.perf_counter()-start
        save()
    return report


if __name__ == "__main__":
    result = asyncio.run(evaluate())
    print(json.dumps({k: v for k, v in result.items() if k not in {"rows", "stability", "dataset"}}, indent=2))
    raise SystemExit(0 if result["status"] == "EVALUATED_PILOT" else 1)
