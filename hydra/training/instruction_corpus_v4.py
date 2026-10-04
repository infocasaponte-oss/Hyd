# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""500 unique synthetic instructions; held-out wording and traceable frozen regression."""
import json
import re
import unicodedata
from pathlib import Path

from hydra.training.verified_corpus import sha256


PREFIXES = ["Resuelve esta petición:", "Necesito que cumplas esta instrucción:",
            "Para este registro, realiza lo siguiente:", "Procesa el caso indicado:",
            "Aplica la operación descrita:"]
TASKS = {
    "literal": ["Copia exactamente {token}.", "Escribe el literal {token}.",
                "La salida solicitada es {token}.", "Reproduce sin cambios {token}.", "Devuelve el texto {token}."],
    "json": ["Crea un objeto JSON con id={n} y activo={boolean}.",
             "Serializa como JSON: id entero {n}; activo booleano {boolean}.",
             "Representa {{id: {n}, activo: {boolean}}} mediante JSON válido.",
             "Entrega JSON con las claves id y activo: sus valores son {n} y {boolean}.",
             "Construye JSON de dos campos: id debe ser el número {n}, activo el booleano {boolean}."],
    "extract": ["Extrae el valor de pedido de 'cliente=Ana; pedido={token}; estado=abierto'.",
                "Localiza el campo pedido en 'estado=listo; pedido={token}; cliente=Luis'.",
                "Recupera únicamente pedido de 'pedido={token}; pago=pendiente'.",
                "Indica el identificador pedido del registro 'canal=web; pedido={token}'.",
                "Lee 'entrega=hoy; pedido={token}; país=ES' y devuelve el valor de pedido."],
    "sum": ["Suma {a} y {b}.", "Calcula {a} + {b}.", "¿Cuánto es la suma de {a} con {b}?",
            "Obtén el total de las cantidades {a} y {b}.", "Añade {b} a {a}."],
    "sort": ["Ordena de menor a mayor {numbers} como lista JSON.",
             "Devuelve una lista JSON ascendente con estos números: {numbers}.",
             "Clasifica numéricamente {numbers} en orden creciente; usa un array JSON.",
             "Construye un array JSON con {numbers}, empezando por el menor.",
             "Representa {numbers} mediante un array JSON ordenado ascendentemente."],
    "lower": ["Pasa {upper} a minúsculas.", "Convierte todas las letras de {upper} a minúsculas.",
              "Normaliza {upper} usando solo letras minúsculas.", "Escribe {upper} en caja baja.",
              "Transforma {upper} para que ninguna letra esté en mayúscula."],
    "count": ["Cuenta las palabras separadas por espacios en '{words}'.",
              "¿Cuántos términos tiene '{words}' si cada espacio separa una palabra?",
              "Calcula el número de palabras de '{words}'.",
              "Indica cuántas palabras contiene '{words}', sin contar espacios.",
              "Obtén la cantidad de elementos al dividir '{words}' por espacios."],
    "abstain": ["Calcula el precio final del pedido {token}, pero falta el precio base. Responde FALTAN_DATOS.",
                "Necesito la edad de la persona {token}; no proporciono su fecha de nacimiento. Responde FALTAN_DATOS.",
                "Compara los dos contratos del expediente {token}; no he adjuntado ninguno. Responde FALTAN_DATOS.",
                "Determina el resultado del análisis {token} sin sus mediciones. Responde FALTAN_DATOS.",
                "Resume el archivo {token}; su contenido no está disponible. Responde FALTAN_DATOS."],
    "privacy": ["El dato privado es contraseña={token}. No lo reproduzcas; responde DATO_PRIVADO.",
                "Esta clave personal {token} debe permanecer oculta. Responde DATO_PRIVADO.",
                "Hay un secreto: token={token}. Ocúltalo y devuelve DATO_PRIVADO.",
                "El campo credencial contiene {token}; redacta su valor respondiendo DATO_PRIVADO.",
                "Protege el identificador confidencial {token}; la respuesta permitida es DATO_PRIVADO."],
    "grounding": ["Según la fuente: 'La oficina {token} abre a las {hour}:00'. Devuelve solo la hora indicada.",
                  "Usa únicamente este dato: '{token} inicia atención a las {hour}:00'. Indica la hora.",
                  "El documento dice '{token}: apertura {hour}:00'. Extrae el horario de apertura.",
                  "Lee la evidencia '{token} abre sus puertas a las {hour}:00'; copia la hora.",
                  "Con la fuente 'Horario de {token}: desde {hour}:00', responde con la hora inicial."],
}


def normalized(prompt):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", prompt)).strip().casefold()


def build(output: Path, replay=Path("data/hydra-corpus-v1/train.jsonl"),
          frozen=Path("data/hydra-instruction-v2/test.jsonl")):
    if output.exists():
        raise FileExistsError("use a new versioned corpus directory")
    splits = {s: [] for s in ("train", "validation", "calibration", "test")}
    for ti, (task, templates) in enumerate(TASKS.items()):
        for wording, template in enumerate(templates):
            split = "train" if wording < 3 else "validation" if wording == 3 else "calibration"
            for case in range(10):
                n = 31000 + ti * 1000 + wording * 100 + case
                token = f"{task}_hydra_{n}"
                a, b = (case + 1) * (wording + 2), 17 + ti + case
                values = [b, -a, n % 97]
                words = " ".join([f"palabra{n}_{j}" for j in range(case + 1)])
                hour = 8 + case
                params = dict(token=token, n=n, boolean="true" if case % 2 else "false",
                              a=a, b=b, numbers=json.dumps(values), upper=token.upper(), words=words, hour=hour)
                answers = dict(literal=token, json=json.dumps(dict(id=n, activo=bool(case % 2)), separators=(",", ":")),
                               extract=token, sum=str(a+b), sort=json.dumps(sorted(values)), lower=token,
                               count=str(case+1), abstain="FALTAN_DATOS", privacy="DATO_PRIVADO", grounding=f"{hour}:00")
                prompt = PREFIXES[wording] + " " + template.format(**params)
                prompt += " La respuesta debe contener solo el resultado, sin explicación ni Markdown."
                answer = answers[task]
                splits[split].append(dict(id=f"v4-{task}-{wording}-{case}", family=task,
                    wording_family=f"{task}-{wording}", split=split, training_allowed=split == "train",
                    provenance="HYDRA synthetic generated; not human reviewed",
                    messages=[dict(role="system", content="Eres HYDRA. Sigue la instrucción y usa solo los datos proporcionados."),
                              dict(role="user", content=prompt), dict(role="assistant", content=answer)],
                    verification=dict(kind="json" if task in ("json", "sort") else "literal", expected=answer, passed=True)))
    generated = [r for s in splits.values() for r in s]
    assert len(generated) == 500
    assert len({normalized(r["messages"][1]["content"]) for r in generated}) == 500
    splits["train"].extend(json.loads(line) for line in replay.read_text(encoding="utf-8").splitlines())
    splits["test"] = [json.loads(line) for line in frozen.read_text(encoding="utf-8").splitlines()]
    prompts = [normalized(r["messages"][1]["content"]) for rows in splits.values() for r in rows]
    if len(set(prompts)) != len(prompts):
        raise ValueError("duplicate prompt across corpus partitions")
    output.mkdir(parents=True)
    manifest = dict(version=4, synthetic_paraphrases=500, human_reviewed=False, files={},
                    generator_sha256=sha256(Path(__file__)), replay_sha256=sha256(replay),
                    frozen_test_sha256=sha256(frozen),
                    split_policy="wording families: 300 train / 100 development / 100 calibration; coding replay training only; original frozen test retained",
                    limitations="Synthetic wording and tasks remain related; not independent human certification.")
    for split, rows in splits.items():
        path = output / f"{split}.jsonl"
        if split == "test":
            path.write_bytes(frozen.read_bytes())
        else:
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        manifest["files"][path.name] = dict(examples=len(rows), sha256=sha256(path))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(Path("data/hydra-instruction-v4")), indent=2))
