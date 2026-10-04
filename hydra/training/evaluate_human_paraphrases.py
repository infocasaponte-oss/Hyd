# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compare the v2 head and live Kev on the human-authored independent set."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from hydra.providers.decision import LocalSystemOneProvider
from hydra.training.decision_benchmark import questions
from hydra.training.decision_metrics import metrics
from hydra.training.human_paraphrase_eval import build
from hydra.training.specialists import TextClassifier


async def evaluate(output: Path = Path("data/evaluations/human-paraphrase-v1.json"),
                   classifier_path: Path = Path("models/hydra-decision-v2/classifier.json")) -> dict:
    source = Path("data/human-paraphrase-v1.jsonl")
    manifest = build(source)
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    classifier = TextClassifier.load(classifier_path)
    head_rows = []
    for row in rows:
        probabilities = classifier.predict_proba(row["text"])
        head_rows.append({"id": row["id"], "expected": row["expected"], "selected": max(probabilities, key=probabilities.get),
                          "probabilities": probabilities})
    report = {"status": "RUNNING", "approved": False, "dataset": manifest,
              "head_v2": metrics(head_rows), "kev": [], "limitations": "Human-authored by HYDRA; no external annotator agreement yet."}
    provider = LocalSystemOneProvider(timeout=30)
    try:
        card = await provider.client.get("/v1/models", timeout=5)
        card.raise_for_status()
        report["server"] = next(c for c in card.json()["models"] if c["name"] == provider.model)
        supported = set(questions()["task"]["criteria"])
        for row in rows:
            began = time.perf_counter()
            result = {"id": row["id"], "expected": row["expected"]}
            if row["expected"] not in supported:
                result.update(status="unsupported_label", passed=False)
            else:
                answer = (await provider.decide(row["text"], questions()))["answers"]["task"]
                result.update(status="evaluated", selected=answer["choice"], probabilities=answer["probabilities"],
                              passed=answer["choice"] == row["expected"])
            result["latency_ms"] = (time.perf_counter() - began) * 1000
            report["kev"].append(result)
        compatible = [row for row in report["kev"] if row["status"] == "evaluated"]
        report["kev_compatible"] = {"count": len(compatible), "accuracy": sum(r["passed"] for r in compatible)/len(compatible)} if compatible else None
        report["status"] = "EVALUATED"
    except Exception as exc:
        report.update(status="FAILED", error=type(exc).__name__ + ": " + str(exc))
    finally:
        await provider.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(evaluate()), indent=2, ensure_ascii=False))
