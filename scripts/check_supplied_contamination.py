# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Read HYDRA JSON/JSONL formats and report overlap without deleting source rows."""
import argparse
from pathlib import Path

from hydra.training.evidence_io import write_json
from hydra.training.finetuning_v8 import normalized, question, read_cases
from hydra.training.verified_corpus import sha256


def grams(text: str) -> set[str]:
    text = normalized(text)
    return {text[i:i+5] for i in range(max(1, len(text)-4))}


def audit(data: list[Path], frozen: list[Path], threshold: float) -> dict:
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be in (0, 1]")
    references = [(str(p), question(r), grams(question(r))) for p in frozen for r in read_cases(p)]
    flags = []
    exact = []
    for p in data:
        for row in read_cases(p):
            prompt = question(row)
            tokens = grams(prompt)
            similarity, source, reference = max((len(tokens & g)/max(1,len(tokens | g)),path,text)
                                                for path,text,g in references)
            if normalized(prompt) == normalized(reference):
                exact.append(dict(id=row.get("id"), source=str(p), reference_source=source))
            if similarity >= threshold:
                flags.append(dict(id=row.get("id"), source=str(p), prompt=prompt, similarity=similarity,
                                  reference_source=source, reference=reference))
    return dict(exact_overlap=exact, lexical_flags=flags, threshold=threshold,
                source_hashes={str(p): sha256(p) for p in data+frozen},
                source_rows_changed=False,
                limitation="Lexical filter only; no guarantee against semantic contamination")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--datos", type=Path, nargs="+", required=True)
    parser.add_argument("--congeladas", type=Path, nargs="+", required=True)
    parser.add_argument("--umbral", type=float, default=.6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("preserve existing audit")
    result = audit(args.datos,args.congeladas,args.umbral)
    write_json(args.output,result)
    print(f"Exact overlaps: {len(result['exact_overlap'])}; lexical flags: {len(result['lexical_flags'])}")
    if result["exact_overlap"]:
        raise SystemExit(1)
