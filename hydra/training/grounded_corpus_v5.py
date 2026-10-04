# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Grounded corpus v5: v4 with a consistent import rule and import-specific hard negatives.

On the development tests the v5 candidate (trained on v4) still failed code_imports in five ways:
it listed "." for ``from . import xyz`` (the question's rule said "only X counts" while the label
was ".xyz"), dropped ``datetime`` in ``from datetime import datetime``, listed the imported names
of ``from math import radians, cos``, stopped early in lists of five or more modules and invented
parent packages. v5 states the relative case in the rule, raises the import quota to 480 and takes
half of it from snippets with those traps. Everything else is v4 (balanced repeal family, eight
training wordings, document splits).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

from hydra.corpus.gates import PrivacyGate
from hydra.training.grounded_corpus_v1 import (
    PERMISSIVE, SPLITS, SYSTEM, boe_candidates, boe_url, contract, length_check, read_jsonl, source_sha256,
    split_for,
)
from hydra.training.grounded_corpus_v2 import IMPORT_RULE, QUOTAS, code_candidates, verify
from hydra.training.grounded_corpus_v3 import QUESTIONS as QUESTIONS_V3, WORDING
from hydra.training.grounded_corpus_v4 import REPEALED_SHARE
from hydra.training.grounded_corpus_v1 import parse
from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256

IMPORT_RULE_V5 = (" Enuméralos en el orden en que aparecen; en from X import Y cuenta solo el módulo X "
                  "(no los nombres Y), y en un import relativo sin módulo, como from . import Y o "
                  "from .. import Y, el módulo son los puntos seguidos de Y (.Y, ..Y).")
QUESTIONS = {family: tuple(q.replace(IMPORT_RULE, IMPORT_RULE_V5) for q in questions) if family == "code_imports"
             else questions for family, questions in QUESTIONS_V3.items()}
QUOTAS_V5 = dict(QUOTAS) | {"code_imports": 480}


def import_traps(tree: ast.Module) -> bool:
    """Snippets with the import patterns the v5 candidate got wrong."""
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = sum(len(n.names) if isinstance(n, ast.Import) else 1 for n in nodes)
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names]
            if node.module is None or len(names) > 1 or node.module.split(".")[-1] in names:
                return True
            if "." in node.module:  # dotted package: the candidate invented parent packages
                return True
        elif any("." in a.name for a in node.names):
            return True
        if any(a.asname for a in node.names):
            return True
    return modules >= 5


def code_candidates_v5(record: dict, absent_name: str):
    candidates, traps = code_candidates(record, absent_name)
    if candidates:
        code = candidates[0][2].split("```python\n", 1)[1].rsplit("\n```", 1)[0]
        # keep v2's import traps (plain + from imports, nested imports) and add v5's
        traps = dict(traps) | {"imports": bool(traps.get("imports")) or import_traps(parse(code))}
    return candidates, traps


REPO_DATA = Path(__file__).resolve().parents[2] / "data"


def sealed_holdout_ids(root: Path = REPO_DATA) -> set[str]:
    """Documents of every sealed holdout: they must never enter a training corpus.

    Anchored to the repository's data folder (not the working directory) and fails closed: a build
    that finds no sealed holdout must pass ``exclude_ids`` explicitly.
    """
    holdouts = sorted(root.glob("hydra-grounded-holdout-*/holdout.jsonl"))
    if not holdouts:
        raise FileNotFoundError(f"no sealed holdout under {root}; pass exclude_ids explicitly")
    ids: set[str] = set()
    for holdout in holdouts:
        ids.update(json.loads(line)["provenance"]["document_id"]
                   for line in holdout.read_text(encoding="utf-8").splitlines() if line.strip())
    return ids


def build(output: Path, boe: Path, code: Path, quotas: dict[str, int] | None = None, per_document: int = 2,
          tokenizer: Path | None = None, max_tokens: int = 768, repealed_share: float = REPEALED_SHARE,
          exclude_ids: set[str] | None = None) -> dict:
    if output.exists():
        raise FileExistsError("use a new versioned corpus")
    exclude_ids = sealed_holdout_ids() if exclude_ids is None else exclude_ids
    quotas = dict(quotas or QUOTAS_V5)
    if set(quotas) != set(QUESTIONS) or min(quotas.values()) < 1 or per_document < 1:
        raise ValueError("a positive quota for every family and a positive per_document are required")
    gate = PrivacyGate()
    fits, length_policy = length_check(tokenizer, max_tokens)
    stats = {"privacy_rejected": 0, "verification_failed": 0, "utf8_rejected": 0, "too_long": 0}
    used = dict.fromkeys(QUESTIONS, 0)
    hard = dict.fromkeys(("code_functions", "code_imports"), 0)
    # boe_repealed: at least `repealed_share` "Sí" answers, so a model that always says "No" cannot pass.
    repeal_caps = {"si": quotas["boe_repealed"] - int(quotas["boe_repealed"] * (1 - repealed_share)),
                   "no": int(quotas["boe_repealed"] * (1 - repealed_share))}
    repeal_used = {"si": 0, "no": 0}
    splits: dict[str, list[dict]] = {s: [] for s in SPLITS}
    seen_prompts: set[str] = set()

    def admit(document_id: str, candidates, provenance: dict, only: set[str] | None = None,
              traps: dict[str, bool] | None = None) -> None:
        if document_id in exclude_ids:
            return
        taken = 0
        for family, fields, source, answer in sorted(candidates, key=lambda c: used[c[0]] / quotas[c[0]]):
            if taken >= per_document or used[family] >= quotas[family] or (only and family not in only):
                continue
            polarity = ("si" if answer.startswith("Sí") else "no") if family == "boe_repealed" else None
            if polarity and repeal_used[polarity] >= repeal_caps[polarity]:
                continue
            if "�" in source or "Ã" in source:
                stats["utf8_rejected"] += 1
                continue
            _, credential, pii = gate.scan_text(source + "\n" + answer)
            if credential or pii:
                stats["privacy_rejected"] += 1
                continue
            if not verify(family, fields, source, answer):
                stats["verification_failed"] += 1
                continue
            split = split_for(document_id)
            choices = WORDING[split]
            wording = choices[int(hashlib.sha256((document_id + family).encode()).hexdigest(), 16) % len(choices)]
            prompt = contract(QUESTIONS[family][wording].format(**fields))
            messages = [{"role": "system", "content": SYSTEM + source},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": answer}]
            if not fits(messages):
                stats["too_long"] += 1
                continue
            key = normalized(SYSTEM + source + prompt)
            if key in seen_prompts:
                continue
            seen_prompts.add(key)
            trap = bool(traps and traps.get(family.removeprefix("code_")))
            splits[split].append({
                "id": f"grounded-v5-{family}-{used[family]}", "family": family,
                "wording_family": f"{family}-{wording}", "split": split, "training_allowed": split == "train",
                "messages": messages, "hard_negative": trap,
                "verification": {"kind": "deterministic_extractive", "passed": True,
                                 "source_sha256": hashlib.sha256(source.encode()).hexdigest()},
                "provenance": provenance,
            })
            used[family] += 1
            if polarity:
                repeal_used[polarity] += 1
            if trap and family in hard:
                hard[family] += 1
            taken += 1

    boe_rows, boe_sha = read_jsonl(boe)
    boe_records = sorted(boe_rows, key=lambda r: hashlib.sha256(r["document_id"].encode()).hexdigest())
    for record in boe_records:
        if all(used[f] >= quotas[f] for f in QUESTIONS if f.startswith("boe_")):
            break
        admit(record["document_id"], boe_candidates(record), {
            "source": "BOE datos abiertos, legislación consolidada", "document_id": record["document_id"],
            "url": boe_url(record["document_id"]), "license": "Reutilización de datos del BOE con cita de la fuente",
            "date_updated": (record.get("metadata") or {}).get("fecha_actualizacion")})

    code_rows, code_sha = read_jsonl(code)
    code_records = [r for r in code_rows if set(r.get("detected_licenses") or []) and
                    set(r["detected_licenses"]) <= PERMISSIVE]
    code_records.sort(key=lambda r: hashlib.sha256(r["id"].encode()).hexdigest())
    prepared = []
    for i, record in enumerate(code_records):
        absent = f"calcular_{['total', 'media', 'indice', 'resumen', 'saldo'][i % 5]}_{i % 97}"
        candidates, traps = code_candidates_v5(record, absent)
        if candidates:
            prepared.append((record, candidates, traps))

    def provenance(record: dict) -> dict:
        return {"source": "common-pile/stackv2_edu_filtered", "document_id": record["id"],
                "repository": record["repo_name"], "path": record["path"], "revision_id": record.get("revision_id"),
                "license": record["detected_licenses"]}

    # Pass 1: half of the function/import quota from snippets with the distractors that fooled v1.
    hard_target = {f: quotas[f] // 2 for f in hard}
    for record, candidates, traps in prepared:
        families = {f for f in hard if traps.get(f.removeprefix("code_")) and used[f] < hard_target[f]}
        if families:
            admit(record["id"], candidates, provenance(record), only=families, traps=traps)
    # Pass 2: every family, ordinary snippets included, until the quotas are met.
    for record, candidates, traps in prepared:
        if all(used[f] >= quotas[f] for f in QUESTIONS if f.startswith("code_")):
            break
        admit(record["id"], candidates, provenance(record), traps=traps)

    external = Path("data/external-evaluation-v2/cases.json")
    if external.exists():
        held_out = {normalized(row["prompt"]) for row in json.loads(external.read_text(encoding="utf-8-sig"))}
        if held_out.intersection(normalized(r["messages"][1]["content"]) for r in splits["train"]):
            raise ValueError("external evaluation leaked into training")

    output.mkdir(parents=True)
    manifest = {
        "version": "grounded-v5", "kind": "source_grounded_verified", "approved": False, "human_reviewed": False,
        "independent_test": False, "generator_sha256": source_sha256(Path(__file__)),
        "helpers_sha256": {name: source_sha256(Path(__file__).with_name(name)) for name in
                           ("grounded_corpus_v1.py", "grounded_corpus_v2.py", "grounded_corpus_v3.py", "grounded_corpus_v4.py")},
        "inputs": {"boe": {"path": str(boe), "sha256": boe_sha, "records": len(boe_records)},
                   "code": {"path": str(code), "sha256": code_sha, "permissive_records": len(code_records)}},
        "split_policy": "same document hash buckets as grounded-v1 (80/7/6/7); training uses wordings 0,1,5-10, validation 2, calibration 4, test 3",
        "length_policy": length_policy, "quotas": quotas, "families": used, "hard_negatives": hard,
        "rejections": stats, "files": {},
        "excluded_sealed_holdout_documents": len(exclude_ids),
        "changes_from_v4": ["documents of every sealed holdout are excluded", "code_imports rule states the relative case (from . import Y -> .Y) that the label already used", "code_imports quota 480 (was 320), half from snippets with the traps the v5 candidate failed: same-name from-imports, several names in one from-import, five or more modules, module-less relative imports, aliases"],
        "repeal_balance": repeal_used,
        "limitations": ("Extractive questions over a single excerpt; verifies faithfulness to the excerpt, not legal "
                        "or programming advice. Code snippets keep repository, path and licence for attribution. "
                        "Not human reviewed."),
    }
    for split, rows in splits.items():
        path = output / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        manifest["files"][path.name] = {"examples": len(rows), "sha256": sha256(path)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest





if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/hydra-grounded-v5"))
    parser.add_argument("--boe", type=Path, default=Path("data/sources/boe/boe_legislacion_consolidada.jsonl"))
    parser.add_argument("--code", type=Path, default=Path("data/sources/code/stackv2_edu_python_sample.jsonl"))
    parser.add_argument("--tokenizer", type=Path, default=None, help="tokenizer.json of the base model")
    parser.add_argument("--max-tokens", type=int, default=768)
    parser.add_argument("--holdout-root", type=Path, default=REPO_DATA,
                        help="folder holding hydra-grounded-holdout-*/ (fails if none is found)")
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.boe, args.code, tokenizer=args.tokenizer, max_tokens=args.max_tokens,
                           exclude_ids=sealed_holdout_ids(args.holdout_root)), indent=2, ensure_ascii=False))
