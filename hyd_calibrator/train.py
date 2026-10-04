# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Train a routing candidate from the explicitly admitted training partition."""

import hashlib
import json
from pathlib import Path

from .atomic import write_text_atomic
from .contract import CRITERIA
from .evaluation import load_rows
from .model import CandidateRanker


def train(dataset: Path, out: Path, epochs=80, state_dims=512, option_dims=128):
    if out.exists():
        raise ValueError("output directory already exists")
    if type(epochs) is not int or not 1 <= epochs <= 1000:
        raise ValueError("epochs must be an integer between 1 and 1000")
    if state_dims not in (512, 1024) or option_dims not in (128, 256):
        raise ValueError("unsupported model dimensions")
    rows = load_rows(dataset)
    licenses = set()
    for row in rows:
        rights = row.get("rights", {})
        if row.get("split") != "train" or row.get("training_allowed") is not True or row.get("consent") is not True:
            raise ValueError("training requires the consented training partition")
        if not isinstance(rights, dict) or rights.get("verified") is not True:
            raise ValueError("declared source rights required")
        license_name = rights.get("license")
        if not isinstance(license_name, str) or not license_name.strip():
            raise ValueError("declared source license required")
        licenses.add(license_name)
    targets = [row["output"]["task_type"] for row in rows]
    if set(targets) != set(CRITERIA):
        raise ValueError("training partition must cover all routing labels")
    model = CandidateRanker(state_dims, option_dims)
    model.fit([row["input"]["query"] for row in rows], targets, CRITERIA, epochs)
    model.training = {
        "criteria": CRITERIA,
        "source_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "examples": len(rows),
        "epochs": epochs,
        "seed": 42,
        "rights_licenses": sorted(licenses),
        "rights_basis": "source-declared",
    }
    out.mkdir(parents=True, exist_ok=False)
    model.save(out / "model.json")
    result = {
        "format": "hyd-training-run/1",
        "model_sha256": model.revision,
        "training": model.training,
        "state_dims": state_dims,
        "option_dims": option_dims,
        "status": "UNCALIBRATED",
        "authority": False,
        "independent_test": False,
    }
    write_text_atomic(out / "training.json", json.dumps(result, indent=2, allow_nan=False))
    return result
