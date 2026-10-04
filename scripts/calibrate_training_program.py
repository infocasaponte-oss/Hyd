# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Fit classifier temperature on an explicitly reserved, artifact-bound split."""
import argparse
import json
from pathlib import Path
from hydra.training.calibration import fit_temperature, risk_coverage
from hydra.training.verified_corpus import sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if data.get("split") != "calibration" or not data.get("artifact_sha256"):
        raise ValueError("reserved calibration split and artifact hash required")
    report = fit_temperature(data["logits"], data["labels"])
    report["risk_coverage"] = risk_coverage(data["logits"], data["labels"], report["temperature"])
    report.update(artifact_sha256=data["artifact_sha256"], input_sha256=sha256(args.input),
                  runtime=data.get("runtime"), template_sha256=data.get("template_sha256"),
                  quantization=data.get("quantization"), split="calibration")
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
