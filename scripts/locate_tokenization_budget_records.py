# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Identify unsupported spans without allocating whole-document BPE token arrays."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from hyd_calibrator.acquisition_snapshot import file_hash
from hyd_calibrator.bounded_sentencepiece import BoundedSentencePiece
from hyd_calibrator.corpus_census import write_report


def locate(snapshot, model, out):
    snapshot, model, out = Path(snapshot), Path(model), Path(out)
    if out.exists():
        raise ValueError("choose a new output")
    manifest_path = snapshot / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    if manifest.get("complete") is not True or manifest.get("format") != "hyd-acquisition-snapshot/1":
        raise ValueError("complete snapshot required")
    tokenizer_hash = file_hash(model)
    processor = BoundedSentencePiece(model)
    if not processor.supported:
        raise ValueError("unsupported tokenizer")
    records = []
    for bucket in ("candidates", "duplicates", "review"):
        path = snapshot / f"{bucket}.jsonl.gz"
        if file_hash(path) != manifest["output_sha256"][bucket]:
            raise ValueError("snapshot hash mismatch")
        rows = 0
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                rows += 1
                wrapper = json.loads(line)
                row = wrapper["original"]
                text = row["text"]
                digest = hashlib.sha256(text.encode()).hexdigest()
                if digest != wrapper["verbatim_text_sha256"] or wrapper["bucket"] != bucket:
                    raise ValueError("record integrity mismatch")
                if len(text) <= processor.span_chars:
                    continue
                try:
                    for _ in processor.spans(text):
                        pass
                except ValueError as error:
                    records.append({"bucket": bucket, "source": row.get("source"),
                                    "verbatim_text_sha256": digest, "characters": len(text),
                                    "reason": str(error), "training_allowed": False})
        if rows != manifest["counts"][bucket] or file_hash(path) != manifest["output_sha256"][bucket]:
            raise ValueError("snapshot changed or count mismatch")
    if manifest_path.read_bytes() != original_manifest or file_hash(model) != tokenizer_hash:
        raise ValueError("manifest or tokenizer changed")
    result = {"format": "hyd-tokenization-budget-diagnostics/1", "complete": True,
              "training_allowed": False, "tokenizer_sha256": tokenizer_hash,
              "snapshot_manifest_sha256": hashlib.sha256(original_manifest).hexdigest(),
              "records": records, "limitations": ["No token counts or text content are emitted.",
              "Records remain preserved; filter or revise preprocessing and recount before training."]}
    write_report(out, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(locate(args.snapshot, args.tokenizer, args.out), ensure_ascii=False))
