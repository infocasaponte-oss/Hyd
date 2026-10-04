# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Strict scoring and source-preserving preparation of the supplied v8 corpus."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from hydra.training.evidence_io import write_json
from hydra.training.json_match import matching_json
from hydra.training.verified_corpus import sha256


def read_cases(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(obj, dict):
        obj = obj["cases"]
    if not isinstance(obj, list) or not obj:
        raise ValueError("expected nonempty case list")
    return obj


def question(row: dict) -> str:
    return row.get("question") or row.get("prompt") or next(
        m["content"] for m in row["messages"] if m["role"] == "user")


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def score(row: dict, output: str) -> bool | None:
    """None requires semantic review; never certify using keyword presence."""
    ref = row.get("answer", row.get("expected_response"))
    if ref is None or row.get("category") == "tecnico":
        return None
    if row.get("subtype") == "lista_n":
        return None  # a list of fruits requires content review, not just bullet counting
    if row.get("subtype") == "json":
        try:
            return matching_json(json.loads(output.strip()), json.loads(ref))
        except (ValueError, TypeError):
            return False
    if row.get("category") == "razonamiento":
        expected = re.findall(r"^Respuesta:\s*(.+)$", ref, re.M)
        actual = re.findall(r"^Respuesta:\s*(.+)$", output, re.M)
        if len(expected) != 1 or len(actual) > 1:
            return False
        final = actual[0] if actual else output.strip()
        if row.get("subtype") == "precio_unitario":
            def pack(text):
                match = re.fullmatch(r"(?:el\s+)?pack\s+([ab])\.?", normalized(text))
                return match.group(1) if match else None
            return pack(final) is not None and pack(final) == pack(expected[0])
        if row.get("subtype") in {"porcentajes", "distancia", "edades", "cajas", "combinatoria", "trabajo"}:
            def number(text):
                match = re.fullmatch(r"([+-]?\d+(?:[.,]\d+)?)\s*(€|euros?|km|h|horas?)?", normalized(text))
                if not match:
                    return None
                unit = match.group(2)
                unit = "€" if unit in {"euro","euros","€"} else "h" if unit in {"h","hora","horas"} else unit
                return Decimal(match.group(1).replace(",",".")), unit
            a,b = number(final),number(expected[0])
            if a is not None and b is not None:
                return a[0] == b[0] and (not a[1] or not b[1] or a[1] == b[1])
        return normalized(final) == normalized(expected[0])
    # Preserve case: uppercase requests must not accept lowercase answers.
    return output.strip() == ref.strip()


def prepare(source: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("use a new candidate corpus directory")
    train, validation = read_cases(source/"train.jsonl"), read_cases(source/"val.jsonl")
    all_rows = train + validation
    if len({normalized(question(r)) for r in all_rows}) != len(all_rows):
        raise ValueError("duplicate or overlapping supplied questions")
    for row in all_rows:
        if row["messages"] != [dict(role="user", content=row["question"]),
                               dict(role="assistant", content=row["answer"])]:
            raise ValueError("question/answer mismatch with chat messages")
    # The original validation remains development-only. Reserve training rows
    # by subtype before training, including JSON and technical concepts.
    grouped = defaultdict(list)
    for row in train:
        grouped[(row["category"], row["subtype"])].append(row)
    new_train, calibration = [], []
    for key in sorted(grouped):
        group = sorted(grouped[key], key=lambda r: r["id"])
        count = 8 if key[0] == "tecnico" else 1
        calibration.extend(group[:count])
        new_train.extend(group[count:])
    # Separate generated JSON development examples, not derived from test cases.
    json_dev = []
    for i in range(8):
        obj = {"item": f"pieza_{810+i}", "count": 73+i, "available": i % 2 == 0}
        prompt = (f'Devuelve únicamente JSON con item="{obj["item"]}", count={obj["count"]} '
                  f'(entero) y available={str(obj["available"]).lower()} (booleano).')
        answer = json.dumps(obj, ensure_ascii=False)
        json_dev.append(dict(id=f"v8-json-dev-{i}", category="instrucciones", subtype="json",
                             question=prompt, answer=answer,
                             messages=[dict(role="user", content=prompt), dict(role="assistant", content=answer)]))
    validation += json_dev
    parent = Path("data/hydra-instruction-v7-contract-v2")
    original_manifest = json.loads((parent/"manifest.json").read_text(encoding="utf-8"))
    for name, entry in original_manifest["files"].items():
        if sha256(parent/name) != entry["sha256"]:
            raise ValueError("parent corpus modified")
    destination.mkdir(parents=True)
    corrections = []
    def adapt(row, split):
        row = dict(row)
        # Restrict overbroad technical claims without using frozen answers.
        answer = row["answer"]
        if row["category"] == "tecnico" and "tipo sea inmutable" in row["question"]:
            answer = ("Un objeto inmutable no puede modificarse después de crearse. int, float, str, tuple y "
                      "frozenset son inmutables; list, dict y set son mutables. Una tupla puede contener objetos "
                      "mutables: no se pueden cambiar sus referencias, pero sí esos objetos. Ser inmutable "
                      "no basta para ser clave de diccionario: también debe ser hashable, incluidos sus elementos.")
        if answer != row["answer"]:
            corrections.append(dict(id=row["id"], original=row["answer"], corrected=answer))
        row.update(id="v8-supplied-"+row["id"], split=split, training_allowed=split == "train",
                   provenance="User supplied synthetic corpus; reviewed by code audit, not independent human test",
                   answer=answer, family="supplied-"+row["category"],
                   messages=[dict(role="user", content=row["question"]), dict(role="assistant", content=answer)])
        return row
    additions = {"train": [adapt(r, "train") for r in new_train],
                 "validation": [adapt(r, "validation") for r in validation],
                 "calibration": [adapt(r, "calibration") for r in calibration], "test": []}
    files = {}
    for split, added in additions.items():
        name = split+".jsonl"
        inherited = (parent/name).read_bytes()
        extra = "".join(json.dumps(row, ensure_ascii=False)+"\n" for row in added).encode("utf-8")
        (destination/name).write_bytes(inherited+extra)
        files[name] = dict(examples=len(read_cases(destination/name)), sha256=sha256(destination/name))
    write_json(destination/"supplied-development.json", dict(cases=additions["validation"]))
    write_json(destination/"supplied-calibration.json", dict(cases=additions["calibration"]))
    manifest = dict(version=8, files=files, parent_manifest_sha256=sha256(parent/"manifest.json"),
                    human_reviewed=False, approved=False, source_files={p.name: sha256(p) for p in source.iterdir() if p.is_file()},
                    new_examples={k: len(v) for k, v in additions.items()},
                    split_policy="Supplied validation stays development; subtype-reserved training rows become calibration; parent replay unchanged",
                    limitations="Known synthetic corpus; semantic correctness and independent certification require human review",
                    corrections=corrections,
                    new_subtypes={k: dict(Counter(r.get("subtype") for r in v)) for k,v in additions.items()})
    write_json(destination/"manifest.json", manifest)
    return manifest
