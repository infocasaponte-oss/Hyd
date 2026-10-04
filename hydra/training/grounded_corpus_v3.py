# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Grounded corpus v3: v2 plus question-wording variety for robustness to unseen phrasings.

Evaluating the v2 candidate (hydra-program-v3-grounded) on grounded-v1's test showed code_imports
5->9/12 and code_functions 17->19/21, but boe_repealed fell 9->4/9: with only two training
wordings per family, the held-out imperative wording ("Comprueba en los metadatos...") produced
garbled answers. v3 trains every family on eight wordings (yes/no questions, imperatives,
indirect forms); validation (2), calibration (4) and test (3) keep their held-out wordings, so
results stay comparable with v1/v2. Extraction, answers, verification, quotas and splits come
from v2 unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from hydra.corpus.gates import PrivacyGate
from hydra.training.grounded_corpus_v1 import (
    PERMISSIVE, SPLITS, SYSTEM, boe_candidates, boe_url, contract, length_check, read_jsonl, source_sha256,
    split_for,
)
from hydra.training.grounded_corpus_v2 import (
    FUNCTION_RULE, IMPORT_RULE, QUESTIONS as QUESTIONS_V2, QUOTAS, code_candidates, verify,
)
from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256

# Train-only wordings, appended after v2's five (indices 5-10). Every boe_repealed wording asks
# "is it repealed?" so the Sí/No answer keeps its meaning.
EXTRA = {
    "boe_heading": (
        "Necesito saber cómo se llama el artículo {art} de {norm}.",
        "Busca en la fuente el título del artículo {art} de {norm}.",
        "¿Qué nombre recibe el artículo {art} de {norm}?",
        "Del artículo {art} de {norm}, dame solo su título y la fuente.",
        "Consulta la fuente e indica el rótulo del artículo {art} de {norm}.",
        "¿Bajo qué título aparece el artículo {art} en {norm}?",
    ),
    "boe_sections": (
        "Comprueba cuántos apartados numerados tiene el artículo {art} de {norm}.",
        "Necesito el número de apartados numerados del artículo {art} de {norm}.",
        "¿El artículo {art} de {norm} cuántos apartados con número contiene?",
        "Revisa el artículo {art} de {norm} y di cuántos apartados numerados tiene.",
        "Indica la cantidad de apartados numerados del artículo {art} de {norm}.",
        "Según el texto, ¿cuántos apartados enumerados hay en el artículo {art} de {norm}?",
    ),
    "boe_quote": (
        "Cita sin modificar el apartado {sec} del artículo {art} de {norm}.",
        "Necesito el texto exacto del apartado {sec} del artículo {art} de {norm}.",
        "Copia palabra por palabra el apartado {sec} del artículo {art} de {norm}.",
        "Busca el apartado {sec} del artículo {art} de {norm} y transcríbelo íntegro.",
        "Dame la redacción literal del apartado {sec} del artículo {art} de {norm}.",
        "Extrae tal cual el apartado {sec} del artículo {art} de {norm}.",
    ),
    "boe_rank_date": (
        "Comprueba en los metadatos el rango y la fecha de publicación de {norm}.",
        "Necesito el rango normativo de {norm} y su fecha en el BOE.",
        "¿Cuál es el rango de {norm} y cuándo apareció publicada en el BOE?",
        "Consulta la ficha y di qué rango tiene {norm} y en qué fecha se publicó.",
        "Indica, según la fuente, el tipo de norma que es {norm} y su día de publicación.",
        "Dame el rango y la fecha de publicación en el BOE de {norm}.",
    ),
    "boe_repealed": (
        "Revisa los metadatos e indica si {norm} consta como derogada.",
        "¿Está derogada {norm} según la fuente?",
        "Comprueba si en los metadatos {norm} aparece como norma derogada.",
        "Necesito saber si consta la derogación de {norm}.",
        "Según la ficha, ¿ha sido derogada {norm}?",
        "Dime si {norm} figura como derogada en los metadatos.",
    ),
    "boe_absent": (
        "Comprueba en la fuente qué dice el artículo {art} de {norm}.",
        "Necesito el contenido del artículo {art} de {norm}.",
        "¿Qué regula exactamente el artículo {art} de {norm}?",
        "Busca el artículo {art} de {norm} y resúmelo.",
        "Indica qué dispone el artículo {art} de {norm}.",
        "Dame un resumen del artículo {art} de {norm} según la fuente.",
    ),
    "code_functions": (
        "Comprueba qué funciones de nivel superior define el código.",
        "Necesito la lista de funciones de primer nivel del fragmento.",
        "Revisa el código y enumera sus funciones de nivel de módulo.",
        "Dime qué funciones están definidas directamente en el módulo.",
        "Indica las funciones de nivel superior que aparecen en el código.",
        "Extrae los nombres de las funciones de primer nivel del fragmento.",
    ),
    "code_imports": (
        "Comprueba qué módulos importa el código.",
        "Necesito la lista de módulos importados por el fragmento.",
        "Revisa las sentencias import y enumera los módulos.",
        "Dime de qué módulos depende el código según sus import.",
        "Indica los módulos que se importan en el fragmento.",
        "Extrae los módulos importados por este código.",
    ),
    "code_params": (
        "Comprueba qué parámetros declara la función `{name}`.",
        "Necesito la lista de parámetros de `{name}`.",
        "Revisa la firma de `{name}` y enumera sus parámetros.",
        "Dime qué argumentos recibe `{name}` según el código.",
        "Indica los parámetros de la función `{name}` en orden.",
        "Extrae los parámetros de la definición de `{name}`.",
    ),
    "code_methods": (
        "Comprueba qué métodos define la clase `{name}`.",
        "Necesito la lista de métodos de `{name}`.",
        "Revisa la clase `{name}` y enumera sus métodos.",
        "Dime qué métodos declara `{name}` en el código.",
        "Indica los métodos de la clase `{name}` en orden.",
        "Extrae los nombres de los métodos de `{name}`.",
    ),
    "code_absent": (
        "Comprueba qué parámetros recibe la función `{name}`.",
        "Necesito saber qué hace la función `{name}` del código.",
        "Revisa el fragmento y explica la función `{name}`.",
        "Dime qué devuelve `{name}` según el código.",
        "Indica cómo se llama a la función `{name}` en el fragmento.",
        "Extrae la firma de la función `{name}`.",
    ),
}
# v2 states the counting rule in every code_functions / code_imports wording; keep doing so.
RULES = {"code_functions": FUNCTION_RULE, "code_imports": IMPORT_RULE}
QUESTIONS = {family: base + tuple(q + RULES.get(family, "") for q in EXTRA[family])
             for family, base in QUESTIONS_V2.items()}

WORDING = {"train": (0, 1, 5, 6, 7, 8, 9, 10), "validation": (2,), "calibration": (4,), "test": (3,)}


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
                "id": f"grounded-v3-{family}-{used[family]}", "family": family,
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
        "version": "grounded-v3", "kind": "source_grounded_verified", "approved": False, "human_reviewed": False,
        "independent_test": False, "generator_sha256": source_sha256(Path(__file__)),
        "helpers_sha256": {name: source_sha256(Path(__file__).with_name(name)) for name in
                           ("grounded_corpus_v1.py", "grounded_corpus_v2.py")},
        "inputs": {"boe": {"path": str(boe), "sha256": boe_sha, "records": len(boe_records)},
                   "code": {"path": str(code), "sha256": code_sha, "permissive_records": len(code_records)}},
        "split_policy": "same document hash buckets as grounded-v1 (80/7/6/7); training uses wordings 0,1,5-10, validation 2, calibration 4, test 3",
        "length_policy": length_policy, "quotas": quotas, "families": used, "hard_negatives": hard,
        "rejections": stats, "files": {},
        "changes_from_v2": ["eight training wordings per family (was two) so answers survive unseen phrasings; validation, calibration and test wordings unchanged"],
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
    parser.add_argument("--output", type=Path, default=Path("data/hydra-grounded-v3"))
    parser.add_argument("--boe", type=Path, default=Path("data/sources/boe/boe_legislacion_consolidada.jsonl"))
    parser.add_argument("--code", type=Path, default=Path("data/sources/code/stackv2_edu_python_sample.jsonl"))
    parser.add_argument("--tokenizer", type=Path, default=None, help="tokenizer.json of the base model")
    parser.add_argument("--max-tokens", type=int, default=768)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.boe, args.code, tokenizer=args.tokenizer, max_tokens=args.max_tokens),
                     indent=2, ensure_ascii=False))
