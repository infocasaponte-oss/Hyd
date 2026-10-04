# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Verified synthetic instruction curriculum, separated from the existing regression test."""
import json
from pathlib import Path

from hydra.training.verified_corpus import sha256


def build(output: Path) -> dict:
    if output.exists():
        raise FileExistsError("versioned corpus already exists")
    output.mkdir(parents=True)
    splits = {"train": [], "validation": [], "test": []}
    system = "Eres HYDRA. Sigue exactamente la instrucción. No añadas información no proporcionada."
    for split, offset, count in [("train", 0, 96), ("validation", 1000, 16), ("test", 2000, 24)]:
        for i in range(count):
            n = offset + i
            # Different instruction families in each partition, not random paraphrase splitting.
            literal = f"clave_{n:04d}"
            prompt = {"train": f"Escribe únicamente este texto, sin comillas: {literal}",
                      "validation": f"Tu respuesta completa debe ser {literal}. No escribas nada más.",
                      "test": f"Copia el contenido situado entre los delimitadores y omite los delimitadores: <<< {literal} >>>"}[split]
            examples = [("literal", prompt, literal)]
            obj = {"id": n, "activo": bool(i % 2)}
            prompt = {"train": f"Devuelve solo JSON válido con id={n} y activo={'true' if obj['activo'] else 'false'}.",
                      "validation": f"Representa en JSON, sin explicación: identificador id {n}, estado activo {obj['activo']}.",
                      "test": f"Convierte este registro a un objeto JSON con las mismas claves: id: {n}; activo: {'sí' if obj['activo'] else 'no'}. No uses Markdown."}[split]
            examples.append(("json", prompt, json.dumps(obj, separators=(",", ":"))))
            for task, question, answer in examples:
                if task == "json":
                    assert json.loads(answer) == obj
                splits[split].append({"id": f"{split}-{task}-{n}", "family": f"{split}-{task}-instruction",
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": question},
                                 {"role": "assistant", "content": answer}],
                    "verification": {"kind": task, "expected": answer, "passed": True},
                    "provenance": "HYDRA deterministic synthetic curriculum"})
    # Replay only the admitted coding training partition, never old test answers.
    source = Path("data/hydra-corpus-v1/train.jsonl")
    splits["train"].extend(json.loads(line) for line in source.read_text(encoding="utf-8").splitlines())
    manifest = {"version": 2, "kind": "synthetic_verified_instruction_curriculum", "files": {},
                "generator": sha256(Path(__file__)), "coding_replay_sha256": sha256(source),
                "limitations": "Synthetic template holdout, not an independent human certification set.",
                "split_policy": "disjoint instruction templates and literal values; coding training replay only"}
    for split, rows in splits.items():
        path = output / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        manifest["files"][path.name] = {"sha256": sha256(path), "examples": len(rows)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(Path("data/hydra-instruction-v2")), indent=2))
