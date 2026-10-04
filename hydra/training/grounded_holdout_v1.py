# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Sealed holdout for grounded candidates: unseen documents and unseen wordings.

grounded-v1/v2/v4 tests were inspected while diagnosing candidates and their failures shaped later
corpora, so they are development/regression sets. This holdout restores an independent check:
- BOE norms absent from every earlier grounded corpus and from the HYDRA Base v0 snapshot;
- code files absent from every earlier grounded corpus (note: they may be in HYDRA Base v0's
  pretraining data, so for HYDRA Base the code families are not independent);
- one new wording per family, never used for training, validation, calibration or test;
- the repeal family balanced (>= 40 % "Sí").
Report only aggregate and per-family scores; do not tune on individual holdout cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from hydra.corpus.gates import PrivacyGate
from hydra.training.grounded_corpus_v1 import (
    PERMISSIVE, SYSTEM, boe_candidates, boe_url, contract, length_check, read_jsonl, source_sha256,
)
from hydra.training.grounded_corpus_v2 import FUNCTION_RULE, IMPORT_RULE, code_candidates, verify
from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256

HOLDOUT_WORDINGS = {
    "boe_heading": "Para el artículo {art} de {norm}, ¿qué título figura en el texto?",
    "boe_sections": "Teniendo delante el artículo {art} de {norm}, ¿cuántos apartados numerados reúne?",
    "boe_quote": "Reproduce fielmente, sin resumir, el apartado {sec} del artículo {art} de {norm}.",
    "boe_rank_date": "A partir de la ficha, ¿qué clase de disposición es {norm} y qué día salió en el BOE?",
    "boe_repealed": "A la vista de los metadatos, ¿{norm} figura derogada?",
    "boe_absent": "Con lo que tienes delante, cuéntame qué dispone el artículo {art} de {norm}.",
    "code_functions": "¿Qué funciones quedan definidas en el nivel más externo del fichero?" + FUNCTION_RULE,
    "code_imports": "¿Qué módulos trae este fichero mediante import?" + IMPORT_RULE,
    "code_params": "¿Con qué parámetros está declarada `{name}`?",
    "code_methods": "¿Qué métodos contiene la clase `{name}`?",
    "code_absent": "¿Qué argumentos espera la función `{name}` de este fichero?",
}
QUOTAS = {"boe_heading": 20, "boe_sections": 20, "boe_quote": 20, "boe_rank_date": 20, "boe_repealed": 20,
          "boe_absent": 20, "code_functions": 15, "code_imports": 15, "code_params": 15, "code_methods": 15,
          "code_absent": 15}
REPEALED_SHARE = 0.4


def used_document_ids(corpora: list[Path]) -> set[str]:
    used: set[str] = set()
    for corpus in corpora:
        for split in corpus.glob("*.jsonl"):
            for line in split.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    used.add(json.loads(line)["provenance"]["document_id"])
    return used


def build(output: Path, boe: Path, code: Path, exclude_corpora: list[Path], exclude_boe_snapshots: list[Path],
          tokenizer: Path | None = None, max_tokens: int = 768) -> dict:
    if output.exists():
        raise FileExistsError("the holdout is sealed: build a new version instead of overwriting")
    used = used_document_ids(exclude_corpora)
    for snapshot in exclude_boe_snapshots:  # e.g. HYDRA Base v0's pretraining input
        used.update(row["document_id"] for row in read_jsonl(snapshot)[0])
    gate = PrivacyGate()
    fits, length_policy = length_check(tokenizer, max_tokens)
    counts = dict.fromkeys(QUOTAS, 0)
    repeal = {"si": 0, "no": 0}
    caps = {"si": QUOTAS["boe_repealed"] - int(QUOTAS["boe_repealed"] * (1 - REPEALED_SHARE)),
            "no": int(QUOTAS["boe_repealed"] * (1 - REPEALED_SHARE))}
    rows: list[dict] = []
    stats = {"excluded_used": 0, "privacy_rejected": 0, "verification_failed": 0, "too_long": 0}

    def admit(document_id: str, candidates, provenance: dict) -> None:
        for family, fields, source, answer in sorted(candidates, key=lambda c: counts[c[0]] / QUOTAS[c[0]]):
            if counts[family] >= QUOTAS[family]:
                continue
            polarity = ("si" if answer.startswith("Sí") else "no") if family == "boe_repealed" else None
            if polarity and repeal[polarity] >= caps[polarity]:
                continue
            _, credential, pii = gate.scan_text(source + "\n" + answer)
            if credential or pii:
                stats["privacy_rejected"] += 1
                continue
            if not verify(family, fields, source, answer):
                stats["verification_failed"] += 1
                continue
            messages = [{"role": "system", "content": SYSTEM + source},
                        {"role": "user", "content": contract(HOLDOUT_WORDINGS[family].format(**fields))},
                        {"role": "assistant", "content": answer}]
            if not fits(messages):
                stats["too_long"] += 1
                continue
            rows.append({"id": f"grounded-holdout-v1-{family}-{counts[family]}", "family": family,
                         "wording_family": f"{family}-holdout", "split": "holdout", "training_allowed": False,
                         "messages": messages, "provenance": provenance,
                         "verification": {"kind": "deterministic_extractive", "passed": True,
                                          "source_sha256": hashlib.sha256(source.encode()).hexdigest()}})
            counts[family] += 1
            if polarity:
                repeal[polarity] += 1
            return  # one example per document keeps the holdout diverse

    boe_rows, boe_sha = read_jsonl(boe)
    for record in sorted(boe_rows, key=lambda r: hashlib.sha256(r["document_id"].encode()).hexdigest()):
        if record["document_id"] in used:
            stats["excluded_used"] += 1
            continue
        admit(record["document_id"], boe_candidates(record), {
            "source": "BOE datos abiertos, legislación consolidada", "document_id": record["document_id"],
            "url": boe_url(record["document_id"]), "license": "Reutilización de datos del BOE con cita de la fuente"})
    code_rows, code_sha = read_jsonl(code)
    records = [r for r in code_rows if set(r.get("detected_licenses") or []) and set(r["detected_licenses"]) <= PERMISSIVE]
    for i, record in enumerate(sorted(records, key=lambda r: hashlib.sha256(("holdout" + r["id"]).encode()).hexdigest())):
        if record["id"] in used:
            stats["excluded_used"] += 1
            continue
        candidates, _ = code_candidates(record, f"obtener_{['saldo', 'indice', 'media'][i % 3]}_{i % 89}")
        admit(record["id"], candidates, {"source": "common-pile/stackv2_edu_filtered", "document_id": record["id"],
                                         "repository": record["repo_name"], "path": record["path"],
                                         "license": record["detected_licenses"]})
    prompts = [normalized(r["messages"][0]["content"] + r["messages"][1]["content"]) for r in rows]
    if len(prompts) != len(set(prompts)):
        raise ValueError("duplicate holdout prompt")
    output.mkdir(parents=True)
    path = output / "holdout.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest = {"version": "grounded-holdout-v1", "sealed": True, "independent_test": True, "approved": False,
                "generator_sha256": source_sha256(Path(__file__)), "families": counts, "repeal_balance": repeal,
                "inputs": {"boe": {"path": str(boe), "sha256": boe_sha}, "code": {"path": str(code), "sha256": code_sha}},
                "excluded_corpora": [str(c) for c in exclude_corpora],
                "excluded_boe_snapshots": [str(s) for s in exclude_boe_snapshots],
                "length_policy": length_policy, "rejections": stats,
                "files": {"holdout.jsonl": {"examples": len(rows), "sha256": sha256(path)}},
                "policy": "report aggregate and per-family scores only; never train or tune on these cases",
                "limitations": "code files may appear in HYDRA Base v0 pretraining data; BOE norms do not"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/hydra-grounded-holdout-v1"))
    parser.add_argument("--boe", type=Path, required=True, help="frozen BOE snapshot newer than every corpus input")
    parser.add_argument("--code", type=Path, default=Path("data/sources/code/stackv2_edu_python_sample.jsonl"))
    parser.add_argument("--exclude-corpus", type=Path, action="append", default=[])
    parser.add_argument("--exclude-boe-snapshot", type=Path, action="append", default=[])
    parser.add_argument("--tokenizer", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.boe, args.code, args.exclude_corpus, args.exclude_boe_snapshot,
                           args.tokenizer), indent=2, ensure_ascii=False))
