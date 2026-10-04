# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""New synthetic JSON contrasts. Held-out prompts and human references are not replayed."""
import json
from pathlib import Path

from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256


PATTERNS = [
    "Serializa el registro con las propiedades id y activo. Identificador: {n}; activación: {state}. Usa un entero y un booleano; entrega un objeto sin comentarios.",
    "La salida es un objeto, no una tupla ni dos valores sueltos. Campos id numérico y activo lógico. Datos: {n}, {state}. Solo el objeto JSON.",
    "Redacta un documento JSON válido con las claves id y activo. El identificador es {n}; el estado es {state}. El estado debe ser true o false.",
    "Guarda {n} como id entero y {state} como activo booleano dentro de un objeto. No escribas texto fuera de las llaves.",
    "Se requiere un objeto de dos propiedades, id y activo. id vale {n}, la activación figura como {state}. Devuelve JSON y convierte el estado en un booleano.",
    "El registro tiene número {n} y estado {state}. Su representación debe tener id de tipo entero y activo de tipo booleano. Devuelve solo la estructura JSON.",
    "Transforma los datos id:{n}, activo:{state} a un objeto serializado. activo debe ser booleano, nunca una cadena. No añadas prosa.",
    "Prepara la respuesta estructurada: clave id, entero {n}; clave activo, booleano equivalente a {state}. Usa llaves, nombres entre comillas y solo estas dos claves.",
    "No respondas únicamente true o false: incluye el identificador {n} en id y el estado {state} en activo. Devuelve un objeto JSON; activo es booleano.",
    "Codifica el estado de la entidad {n}, que consta como {state}. El contrato es id:integer, activo:boolean. Devuelve exclusivamente el objeto.",
    "Construye una ficha serializada con id entero {n} y activo lógico equivalente a {state}. Se requieren ambas propiedades dentro de llaves.",
    "Representa en JSON el identificador {n} y la activación {state}. Emplea exactamente id y activo; convierte la activación a un valor booleano.",
    "Devuelve {{\"id\": número, \"activo\": booleano}} para el identificador {n} y el estado {state}, sustituyendo los tipos por los valores correspondientes.",
    "La API espera un objeto con id y activo. Envía id={n} y traduce {state} a un booleano. No omitas las claves ni las llaves.",
    "Para el dato {n}, {state}, entrega una representación estructurada con las propiedades id numérica y activo booleana. No uses una lista.",
    "Conserva el número {n} bajo id y normaliza el estado {state} bajo activo booleano. Produce un objeto con dos propiedades, sin explicación.",
    "Hay una entidad cuyo id es {n} y cuyo activo se describe como {state}. Serializa ambas propiedades, id y activo; activo debe ser un booleano JSON.",
    "Emite un objeto de dos claves: id lleva el entero {n}, activo lleva el valor lógico de {state}. No emitas valores separados por comas fuera del objeto.",
    "Se indica {state} para la entidad {n}. Responde con las propiedades id y activo dentro de un objeto JSON; normaliza activo a booleano.",
    "La respuesta necesita un objeto completo. Identificador {n}, activación {state}: los nombres son id y activo y sus tipos son entero y booleano.",
]


def build(output: Path, previous=Path("data/hydra-instruction-v5"), version=6):
    if output.exists():
        raise FileExistsError("use a new versioned corpus")
    prior = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
    splits = {}
    for split in ("train", "validation", "calibration", "test"):
        source = previous / f"{split}.jsonl"
        if sha256(source) != prior["files"][source.name]["sha256"]:
            raise ValueError("parent corpus modified")
        splits[split] = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    states = [("sí", True), ("no", False), ("encendido", True), ("apagado", False),
              ("habilitado", True), ("deshabilitado", False), ("true", True), ("false", False)]
    for wording, pattern in enumerate(PATTERNS):
        split = "train" if wording < 14 else "validation" if wording < 17 else "calibration"
        for i in range(16):
            n = 960000 + wording * 100 + i
            state, active = states[i % len(states)]
            answer = json.dumps({"id": n, "activo": active}, separators=(",", ":"))
            splits[split].append(dict(
                id=f"v{version}-json-{wording}-{i}", family="json", wording_family=f"v{version}-json-{wording}",
                split=split, training_allowed=split == "train", provenance="synthetic HYDRA format contrasts, not human authored",
                messages=[dict(role="system", content="Eres HYDRA. Cumple el formato solicitado sin texto adicional."),
                          dict(role="user", content=pattern.format(n=n, state=state)), dict(role="assistant", content=answer)],
                verification=dict(kind="json", expected=answer, passed=True)))
    prompts = [normalized(row["messages"][1]["content"]) for rows in splits.values() for row in rows]
    if len(prompts) != len(set(prompts)):
        raise ValueError("duplicate or overlapping prompt")
    # External references are held out regardless of their authorship declaration.
    external = Path("data/external-evaluation-v2/cases.json")
    if external.exists():
        held_out = {normalized(row["prompt"]) for row in json.loads(external.read_text(encoding="utf-8-sig"))}
        if held_out.intersection(normalized(row["messages"][1]["content"]) for row in splits["train"]):
            raise ValueError("external evaluation leaked into training")
    output.mkdir(parents=True)
    manifest = dict(version=version, files={}, new_synthetic_examples=320, human_reviewed=False,
                    generator_sha256=sha256(Path(__file__)), parent_manifest_sha256=sha256(previous / "manifest.json"),
                    split_policy="14 training / 3 development / 3 calibration wording families; original frozen test unchanged",
                    limitations="Known synthetic regression; does not substitute independent human assessment")
    for split, rows in splits.items():
        path = output / f"{split}.jsonl"
        if split == "test":
            path.write_bytes((previous / path.name).read_bytes())
        else:
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        manifest["files"][path.name] = dict(examples=len(rows), sha256=sha256(path))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(Path("data/hydra-instruction-v6")), indent=2))
