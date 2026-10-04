# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Deterministic, executable Spanish coding curriculum for a HYDRA pilot.

Only the trusted templates below are executed; model-generated code is never run here.
Families, rather than random rows, define the held-out partitions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hydra.core.hashing import sha256_file

SYSTEM = "Eres HYDRA, asistente de programación. Responde con código Python correcto, sin explicaciones."
FAMILIES = {
    "train": {
        "affine": ("Devuelve x multiplicado por {n} y sumado a {k}.", "x", "x * {n} + {k}", lambda x, n, k: x*n+k),
        "threshold": ("Devuelve True si x es mayor o igual que {n}.", "x", "x >= {n}", lambda x, n, k: x>=n),
        "divisible": ("Comprueba si x es divisible por {n}.", "x", "x % {n} == 0", lambda x, n, k: x%n==0),
        "clamp": ("Limita x al intervalo cerrado entre 0 y {n}.", "x", "max(0, min(x, {n}))", lambda x, n, k: max(0,min(x,n))),
        "sum_list": ("Suma los elementos de xs y añade {n}.", "xs", "sum(xs) + {n}", lambda x, n, k: sum(x)+n),
        "filter": ("Devuelve los elementos de xs mayores que {n}, conservando su orden.", "xs", "[x for x in xs if x > {n}]", lambda x,n,k:list(filter(lambda v:v>n,x))),
    },
    "validation": {
        "scale_list": ("Multiplica cada elemento de xs por {n}.", "xs", "[x * {n} for x in xs]", lambda x,n,k:list(map(lambda v:v*n,x))),
    },
    "test": {
        "count": ("Cuenta cuántos elementos de xs son iguales a {n}.", "xs", "xs.count({n})", lambda x,n,k:sum(v==n for v in x)),
        "distance": ("Calcula la distancia absoluta entre x y {n}.", "x", "abs(x - {n})", lambda x,n,k:max(x,n)-min(x,n)),
    },
}


def sha256(path: Path) -> str:
    return sha256_file(path, chunk=8 * 1024 * 1024)


def build(output: Path, per_family: int = 32) -> dict:
    if per_family < 1:
        raise ValueError("per_family must be positive")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "kind": "synthetic_verified_pilot", "generator": sha256(Path(__file__)),
                "limitations": "Small template curriculum; not evidence of general coding quality.",
                "split_policy": "disjoint problem families", "files": {}, "families": {}}
    seen = set()
    for split, families in FAMILIES.items():
        rows = []
        for family, (instruction, arg, expression, oracle) in families.items():
            for i in range(per_family):
                n, k = i+2, i*3+1
                prompt = "Escribe una función solve(" + arg + "). " + instruction.format(n=n, k=k)
                if prompt in seen:
                    raise ValueError("duplicate prompt across corpus")
                seen.add(prompt)
                code = "def solve(" + arg + "):\n    return " + expression.format(n=n,k=k) + "\n"
                scope = {}
                exec(compile(code, "<trusted-curriculum>", "exec"), scope)
                inputs = [-10, 0, 1, n, n+1, 2*n] if arg == "x" else [[], [n], [n, n, 0], [-10, 0, n, n+1]]
                cases = [{"input": x, "expected": oracle(x,n,k)} for x in inputs]
                if not all(scope["solve"](c["input"]) == c["expected"] for c in cases):
                    raise ValueError(f"template {family}-{i} disagrees with its oracle")
                rows.append({"id": f"{family}-{i}", "family": family,
                             "messages": [{"role":"system","content":SYSTEM},
                                          {"role":"user","content":prompt},
                                          {"role":"assistant","content":code}],
                             "verification": {"passed": True, "cases": cases},
                             "provenance": "HYDRA trusted deterministic templates; no external corpus"})
        path = output / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows),encoding="utf-8")
        manifest["files"][path.name] = {"sha256": sha256(path), "examples": len(rows)}
        manifest["families"][split] = list(families)
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/hydra-corpus-v1"))
    parser.add_argument("--per-family", type=int, default=32)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.per_family), indent=2))
