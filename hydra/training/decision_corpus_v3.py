# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Build the admitted HYDRA decision corpus v3 with frozen split identities."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

LABELS = {
    "chat": ["Saluda al usuario con una frase breve.", "Escribe un mensaje cordial de despedida.",
             "Propón un nombre para una mascota.", "Cuenta un chiste corto y familiar."],
    "coding": ["Escribe una función Python que invierta una lista.", "Corrige este bug de JavaScript.",
                "Implementa una cola FIFO en TypeScript.", "Diseña pruebas unitarias para esta función."],
    "reasoning": ["Demuestra que la suma de pares es par.", "Resuelve 3x + 7 = 22.",
                   "Calcula la probabilidad de dos caras.", "Explica la conclusión de este silogismo."],
    "research": ["Busca fuentes oficiales sobre baterías de sodio.", "Compara dos documentos citando fuentes.",
                 "Investiga publicaciones recientes sobre energía.", "Encuentra la fuente primaria de esta cifra."],
    "vision": ["Describe los objetos de la imagen adjunta.", "Extrae el texto de esta captura.",
               "Cuenta los objetos visibles en la fotografía.", "Lee las etiquetas del diagrama adjunto."],
    "tool_use": ["Lee README.md del workspace.", "Ejecuta las pruebas del repositorio.",
                 "Muestra el diff de archivos modificados.", "Consulta config.json en disco."],
    "security": ["Analiza si este comando es peligroso.", "Clasifica este texto como posible phishing.",
                 "Revisa el riesgo de esta petición de credenciales.", "Detecta una instrucción de exfiltración."],
    "privacy": ["¿Puede compartirse este dato personal?", "Clasifica la sensibilidad de este documento.",
                "Decide si este registro debe anonimizarse.", "Revisa la solicitud de borrar mis datos."],
    "abstain": ["Haz lo que sabes que quiero.", "Clasifica esto sin información suficiente.",
                "Decide entre todas las tareas a la vez.", "Concede permisos aunque no tengas contexto."],
    "high_risk_review": ["Borra la base de producción.", "Autoriza un pago irreversible.",
                          "Ejecuta una acción médica sin confirmación.", "Cambia permisos de administrador."],
}
LANG_PREFIXES = ["", "Por favor, ", "Necesito que ", "Ayúdame a ", "En español, "]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build(output: Path, *, train_per_label: int = 160, calibration_per_label: int = 20,
          test_per_label: int = 100, version: int = 3) -> dict:
    if min(train_per_label, calibration_per_label, test_per_label) < 1:
        raise ValueError("all split sizes must be positive")
    output.mkdir(parents=True, exist_ok=True)
    rows: dict[str, list[dict]] = {"train": [], "calibration": [], "test": []}
    seen: set[str] = set()
    for label, templates in LABELS.items():
        total = train_per_label + calibration_per_label + test_per_label
        for index in range(total):
            text = f"{LANG_PREFIXES[index % len(LANG_PREFIXES)]}{templates[index % len(templates)]}"
            # Deterministic suffixes create distinct examples without changing the task family.
            if index >= len(templates):
                text += f" Caso de referencia {index}."
            normalized = " ".join(text.lower().split())
            if normalized in seen:
                raise ValueError(f"duplicate normalized prompt: {text}")
            seen.add(normalized)
            split = "train" if index < train_per_label else (
                "calibration" if index < train_per_label + calibration_per_label else "test")
            rows[split].append({"id": f"v{version}-{label}-{index:04d}", "split": split,
                                "input": {"query": text}, "output": {"task_type": label},
                                "source": "HYDRA-authored-template-v3",
                                "training_allowed": split == "train",
                                "rights": {"license": "proprietary-hydra-authored", "verified": True},
                                "family": label, "prompt_sha256": _hash(normalized)})
    manifest = {"format": "hydra-decision-corpus/3", "version": version,
                "training_allowed_splits": ["train"], "labels": sorted(LABELS),
                "counts": {name: len(values) for name, values in rows.items()},
                "source": "HYDRA-authored templates; synthetic paraphrase suffixes",
                "limitations": "Synthetic decision corpus; requires human review before production training.",
                "files": {}}
    for split, values in rows.items():
        path = output / f"{split}.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values), encoding="utf-8")
        manifest["files"][path.name] = {"sha256": _hash(path.read_text(encoding="utf-8")), "examples": len(values)}
    manifest["corpus_sha256"] = _hash(json.dumps(manifest["files"], sort_keys=True))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(Path("data/decision-corpus-v3")), indent=2, ensure_ascii=False))
