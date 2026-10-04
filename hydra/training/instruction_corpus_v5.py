# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Contrastive boolean normalization and sorting; never replays evaluation answers."""
import json
from pathlib import Path

from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256


PATTERNS = {
    "json": ["Normaliza a JSON este dato de estado: identificador {n}, activo {state}. El estado activo se representa con un booleano; conserva la clave id para el identificador.",
             "Entrega solo JSON con id={n} y activo interpretando {state} como estado lógico, no como texto.",
             "Para el registro id {n}, la activación indicada es {state}. Expresa id numérico y activo booleano en un objeto JSON.",
             "La ficha {n} tiene activación {state}. Serializa solo las claves id y activo; convierte la activación en true o false.",
             "Construye el objeto JSON de id {n} con estado activo {state}. Traduce el estado a un booleano JSON y omite toda explicación."],
    "sort": ["Devuelve solo una lista JSON ascendente de {numbers}. Compara valores numéricos, conserva duplicados y no elimines elementos.",
             "Reorganiza numéricamente {numbers} desde el menor al mayor. Responde solo con el array JSON completo.",
             "Necesito los elementos de {numbers} ordenados de forma creciente; mantén todos, también los repetidos. Devuelve un array JSON.",
             "Orden creciente numérico solicitado para {numbers}. La salida debe ser únicamente el array JSON, con la misma cantidad de elementos.",
             "Coloca {numbers} de menor a mayor, comparando los números y sin descartar repeticiones. Entrega exclusivamente la lista JSON resultante."]}


def build(output: Path, previous=Path("data/hydra-instruction-v4")):
    if output.exists():
        raise FileExistsError("versioned output exists")
    prior = json.loads((previous/"manifest.json").read_text(encoding="utf-8"))
    for filename, entry in prior["files"].items():
        if sha256(previous/filename) != entry["sha256"]:
            raise ValueError("previous corpus modified")
    splits = {s:[json.loads(line) for line in (previous/f"{s}.jsonl").read_text(encoding="utf-8").splitlines()]
              for s in ("train", "validation", "calibration", "test")}
    states = [("sí",True),("no",False),("encendido",True),("apagado",False),("habilitado",True),("deshabilitado",False)]
    for family, patterns in PATTERNS.items():
        for wording, pattern in enumerate(patterns):
            split = "train" if wording < 3 else "validation" if wording == 3 else "calibration"
            for i in range(20):
                n = 83000 + wording*100 + i
                state, active = states[i%len(states)]
                numbers = [101+i, 9+i, -(i+2), 9+i, (i-10)/2, 0]
                if i%2:
                    numbers.reverse()
                prompt = pattern.format(n=n,state=state,numbers=json.dumps(numbers))
                answer = json.dumps(dict(id=n,activo=active) if family == "json" else sorted(numbers),separators=(",", ":"))
                splits[split].append(dict(id=f"v5-{family}-{wording}-{i}",family=family,
                    wording_family=f"v5-{family}-{wording}",split=split,training_allowed=split=="train",
                    provenance="HYDRA synthetic contrastive development, not independent human evaluation",
                    messages=[dict(role="system",content="Eres HYDRA. Cumple el formato solicitado sin texto adicional."),
                              dict(role="user",content=prompt),dict(role="assistant",content=answer)],
                    verification=dict(kind="json",expected=answer,passed=True)))
    prompts = [normalized(r["messages"][1]["content"]) for rows in splits.values() for r in rows]
    if len(set(prompts)) != len(prompts):
        raise ValueError("duplicate prompt")
    output.mkdir(parents=True)
    manifest = dict(version=5,files={},new_synthetic_examples=200,human_reviewed=False,
                    generator_sha256=sha256(Path(__file__)),parent_manifest_sha256=sha256(previous/"manifest.json"),
                    split_policy="training replay only; 120 new training / 40 development / 40 calibration; frozen test byte identical",
                    limitations="Developed against observed task weaknesses; known regression, not independent certification")
    for split, rows in splits.items():
        path = output/f"{split}.jsonl"
        if split == "test":
            path.write_bytes((previous/"test.jsonl").read_bytes())
        else:
            path.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in rows),encoding="utf-8")
        manifest["files"][path.name] = dict(examples=len(rows),sha256=sha256(path))
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(Path("data/hydra-instruction-v5")),indent=2))
