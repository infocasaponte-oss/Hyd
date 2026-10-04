# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Validated input and diagnostics shared by calibration and reporting."""

import hashlib
import json
import math
from pathlib import Path
from .contract import CRITERIA


def load_rows(path, split=None):
    rows, seen = [], set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            text = row["input"]["query"]
            label = row["output"]["task_type"]
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > 50000
                or not isinstance(label, str)
                or label not in CRITERIA
            ):
                raise ValueError("invalid text or label")
            if split and (row.get("split") != split or row.get("training_allowed") is not False):
                raise ValueError("requires non-training calibration partition")
            key = " ".join(text.casefold().split())
            if key in seen:
                raise ValueError("duplicate or conflicting text")
            seen.add(key)
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"line {number}: {error}") from error
        rows.append(row)
    if not rows:
        raise ValueError("empty evaluation partition")
    return rows


def load_calibration(path, model):
    cal = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cal, dict) or cal.get("format") not in ("hyd-calibration/1", "hyd-standalone-calibration/1"):
        raise ValueError("unsupported calibration format")
    if cal.get("model_sha256") != model.revision or cal.get("temperature") != model.temperature:
        raise ValueError("calibration model hash or temperature mismatch")
    if cal.get("criteria") != CRITERIA or model.training.get("criteria") != CRITERIA:
        raise ValueError("routing criteria mismatch")
    if (
        cal["format"] == "hyd-standalone-calibration/1"
        and cal.get("calibrator_implementation_sha256") != implementation_sha256()
    ):
        raise ValueError("calibrator implementation mismatch; recalibrate")
    for name in ("min_confidence", "min_margin"):
        value = cal.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"invalid {name}")
    return cal


def wilson(correct, total):
    if not total:
        return 0.0
    z = 1.96
    p = correct / total
    return (p + z * z / (2 * total) - z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / (
        1 + z * z / total
    )


def selective(confidences, margins, hits, confidence, margin, abstain_all=False):
    chosen = [
        hit for c, m, hit in zip(confidences, margins, hits) if not abstain_all and c >= confidence and m >= margin
    ]
    return {
        "n": len(hits),
        "accepted": len(chosen),
        "correct": sum(chosen),
        "coverage": len(chosen) / len(hits) if hits else 0.0,
        "accuracy": sum(chosen) / len(chosen) if chosen else None,
        "accuracy_wilson_lower_95": wilson(sum(chosen), len(chosen)),
    }


def implementation_sha256():
    digest = hashlib.sha256()
    for name in ("model.py", "contract.py", "evaluation.py", "calibrate.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()
