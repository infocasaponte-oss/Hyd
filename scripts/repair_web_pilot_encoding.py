# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Make an audited new copy of the synthetic fixtures; never mutate trained inputs."""
import json
from pathlib import Path
from hydra.training.verified_corpus import sha256
from hydra.training.program import content_key


def repair(value):
    if isinstance(value, str) and "\u00c3" in value:
        try:
            return value.encode("latin1").decode("utf-8")
        except (UnicodeError, ValueError):
            raise ValueError("mixed encoding requires manual repair")
    if isinstance(value, list):
        return [repair(item) for item in value]
    if isinstance(value, dict):
        return {key: repair(item) for key, item in value.items()}
    return value


if __name__ == "__main__":
    source = Path("data/hydra-web-grounding-v1")
    target = Path("data/hydra-web-grounding-v1-utf8")
    target.mkdir(exist_ok=False)
    entries = {}
    for name in ("train.jsonl", "validation.jsonl", "calibration.jsonl", "test.jsonl"):
        rows = [repair(json.loads(line)) for line in (source / name).read_text(encoding="utf-8").splitlines()]
        for row in rows:
            content_key(row)
        path = target / name
        path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows), encoding="utf-8")
        entries[name] = {"examples": len(rows), "sha256": sha256(path), "source_sha256": sha256(source / name)}
    (target / "manifest.json").write_text(json.dumps({"files": entries, "synthetic": True,
        "approved": False, "repair": "Reversible Latin1/UTF8 source repair; new dataset, old inputs untouched"}, indent=2), encoding="utf-8")
