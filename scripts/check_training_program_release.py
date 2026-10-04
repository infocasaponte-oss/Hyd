# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Check evidence completeness; never deploy or approve automatically."""
import argparse
import json
from pathlib import Path
from hydra.training.program import release_gate
from hydra.training.verified_corpus import sha256


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = release_gate(json.loads(args.evidence.read_text(encoding="utf-8")))
    result.update(evidence_path=str(args.evidence), evidence_sha256=sha256(args.evidence))
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    raise SystemExit(0 if result["eligible"] else 1)
