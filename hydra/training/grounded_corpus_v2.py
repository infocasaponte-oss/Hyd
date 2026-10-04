# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Grounded corpus v2: v1 plus fixes for the code families the v1 candidate got wrong.

Evaluation of the v1 candidate (docs/evidence/grounded-v1-evaluation.json) showed:
- code_imports 5/12: the label was ambiguous ("from sklearn.externals import joblib" -> is
  joblib a module?) and modules were listed alphabetically instead of in reading order.
  v2 states the rule in the question (for ``from X import Y`` only X counts) and lists modules
  in order of appearance.
- code_functions 17/21: methods, nested functions and the ``if __name__`` block were counted
  as top-level functions. v2 says what counts in the question and prefers snippets that
  contain exactly those distractors (hard negatives), with larger quotas for both families.
- the plural typo "funciónes" (now "funciones").
BOE families, splits (same document hash buckets, so v1's test stays out of v2's training)
and verification are unchanged; helpers come from v1.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

from hydra.corpus.gates import PrivacyGate
from hydra.training.grounded_corpus_v1 import (
    PERMISSIVE, QUESTIONS as QUESTIONS_V1, SPLITS, SYSTEM, WORDING, boe_candidates, boe_url, code_snippet,
    code_source, contract, length_check, params, parse, read_jsonl, source_sha256, split_for, ticks,
    verify as verify_v1,
)
from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256

FUNCTION_RULE = " Cuenta solo las definidas con def en el nivel del módulo: no los métodos de clase, ni las funciones anidadas, ni bloques como if __name__."
IMPORT_RULE = " Enuméralos en el orden en que aparecen; en from X import Y cuenta solo el módulo X."

QUESTIONS = dict(QUESTIONS_V1)
QUESTIONS["code_functions"] = tuple(q + FUNCTION_RULE for q in QUESTIONS_V1["code_functions"])
QUESTIONS["code_imports"] = tuple(q + IMPORT_RULE for q in QUESTIONS_V1["code_imports"])

QUOTAS = {"boe_heading": 200, "boe_sections": 200, "boe_quote": 200, "boe_rank_date": 200,
          "boe_repealed": 200, "boe_absent": 200, "code_functions": 320, "code_imports": 320,
          "code_params": 160, "code_methods": 160, "code_absent": 160}


def plural(count: int, singular: str, many: str) -> str:
    return singular if count == 1 else many


def imports_in_order(tree: ast.Module) -> list[str]:
    """Imported modules in reading order; for ``from X import Y`` the module is X."""
    found: list[str] = []
    for node in sorted((n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))),
                       key=lambda n: (n.lineno, n.col_offset)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif node.module:
            found.append("." * node.level + node.module)
        else:  # "from . import util" imports the submodule util
            found += ["." * node.level + alias.name for alias in node.names]
    return list(dict.fromkeys(found))


def distractors(tree: ast.Module) -> dict[str, bool]:
    """Traps that made the v1 candidate miscount top-level functions or imports."""
    top = set(map(id, tree.body))
    nested_defs = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(n) not in top
                      for n in ast.walk(tree))
    main_guard = any(isinstance(n, ast.If) and "__name__" in ast.unparse(n.test) for n in tree.body)
    has_from = any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree))
    has_plain = any(isinstance(n, ast.Import) for n in ast.walk(tree))
    nested_import = any(isinstance(n, (ast.Import, ast.ImportFrom)) and id(n) not in top for n in ast.walk(tree))
    return {"functions": nested_defs or main_guard, "imports": (has_from and has_plain) or nested_import}


def code_candidates(record: dict, absent_name: str) -> tuple[list[tuple[str, dict, str, str]], dict[str, bool]]:
    snippet = code_snippet(record["text"])
    if not snippet:
        return [], {}
    tree = parse(snippet)
    source = code_source(record, snippet)
    out = []
    functions = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if functions:
        out.append(("code_functions", {}, source, f"Define {len(functions)} "
                    f"{plural(len(functions), 'función', 'funciones')} de nivel superior: {ticks(functions)}."))
    modules = imports_in_order(tree)
    if modules:
        out.append(("code_imports", {}, source,
                    f"Importa {len(modules)} {plural(len(modules), 'módulo', 'módulos')}: {ticks(modules)}."))
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and params(n)]
    names = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    unique = [f for f in funcs if names.count(f.name) == 1]
    if unique:
        f = unique[0]
        out.append(("code_params", {"name": f.name}, source,
                    f"La función `{f.name}` recibe los parámetros: {ticks(params(f))}."))
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for c in classes[:1]:
        methods = [n.name for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if methods and [x.name for x in classes].count(c.name) == 1:
            out.append(("code_methods", {"name": c.name}, source, f"La clase `{c.name}` define {len(methods)} "
                        f"{plural(len(methods), 'método', 'métodos')}: {ticks(methods)}."))
    if absent_name not in snippet:
        out.append(("code_absent", {"name": absent_name}, source,
                    f"El código proporcionado no define ninguna función llamada `{absent_name}`, así que no "
                    "puedo responder sobre ella con esta fuente."))
    return out, distractors(tree)


def verify(family: str, fields: dict, source: str, answer: str) -> bool:
    if family != "code_imports":
        return verify_v1(family, fields, source, answer)
    code = source.split("```python\n", 1)[1].rsplit("\n```", 1)[0]
    return re.findall(r"`([^`]+)`", answer) == imports_in_order(parse(code))


def build(output: Path, boe: Path, code: Path, quotas: dict[str, int] | None = None, per_document: int = 2,
          tokenizer: Path | None = None, max_tokens: int = 768) -> dict:
    if output.exists():
        raise FileExistsError("use a new versioned corpus")
    quotas = dict(quotas or QUOTAS)
    if set(quotas) != set(QUESTIONS) or min(quotas.values()) < 1 or per_document < 1:
        raise ValueError("a positive quota for every family and a positive per_document are required")
    gate = PrivacyGate()
    fits, length_policy = length_check(tokenizer, max_tokens)
    stats = {"privacy_rejected": 0, "verification_failed": 0, "utf8_rejected": 0, "too_long": 0}
    used = dict.fromkeys(QUESTIONS, 0)
    hard = dict.fromkeys(("code_functions", "code_imports"), 0)
    splits: dict[str, list[dict]] = {s: [] for s in SPLITS}
    seen_prompts: set[str] = set()

    def admit(document_id: str, candidates, provenance: dict, only: set[str] | None = None,
              traps: dict[str, bool] | None = None) -> None:
        taken = 0
        for family, fields, source, answer in sorted(candidates, key=lambda c: used[c[0]] / quotas[c[0]]):
            if taken >= per_document or used[family] >= quotas[family] or (only and family not in only):
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
                "id": f"grounded-v2-{family}-{used[family]}", "family": family,
                "wording_family": f"{family}-{wording}", "split": split, "training_allowed": split == "train",
                "messages": messages, "hard_negative": trap,
                "verification": {"kind": "deterministic_extractive", "passed": True,
                                 "source_sha256": hashlib.sha256(source.encode()).hexdigest()},
                "provenance": provenance,
            })
            used[family] += 1
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
        candidates, traps = code_candidates(record, absent)
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
        "version": "grounded-v2", "kind": "source_grounded_verified", "approved": False, "human_reviewed": False,
        "independent_test": False, "generator_sha256": source_sha256(Path(__file__)),
        "helpers_sha256": source_sha256(Path(__file__).with_name("grounded_corpus_v1.py")),
        "inputs": {"boe": {"path": str(boe), "sha256": boe_sha, "records": len(boe_records)},
                   "code": {"path": str(code), "sha256": code_sha, "permissive_records": len(code_records)}},
        "split_policy": "same document hash buckets as grounded-v1 (80/7/6/7) and disjoint wording families",
        "length_policy": length_policy, "quotas": quotas, "families": used, "hard_negatives": hard,
        "rejections": stats, "files": {},
        "changes_from_v1": ["code_imports: explicit rule and reading order", "code_functions: explicit rule and "
                            "hard negatives (nested defs, methods, if __name__)", "larger code_functions/"
                            "code_imports quotas", "plural typo 'funciónes' fixed"],
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
    parser.add_argument("--output", type=Path, default=Path("data/hydra-grounded-v2"))
    parser.add_argument("--boe", type=Path, default=Path("data/sources/boe/boe_legislacion_consolidada.jsonl"))
    parser.add_argument("--code", type=Path, default=Path("data/sources/code/stackv2_edu_python_sample.jsonl"))
    parser.add_argument("--tokenizer", type=Path, default=None, help="tokenizer.json of the base model")
    parser.add_argument("--max-tokens", type=int, default=768)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.boe, args.code, tokenizer=args.tokenizer, max_tokens=args.max_tokens),
                     indent=2, ensure_ascii=False))
