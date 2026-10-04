# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""SBOM / MBOM (Model Bill of Materials) / DBOM (Data Bill of Materials).

HYDRA keeps a richer native manifest and exports the interoperable CycloneDX 1.6
format (with ``machine-learning-model`` and ``data`` components and a modelCard) for
customers, audits and partners. ``hm://`` identifiers stay stable when paths change."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

import hydra
from hydra.core.hashing import hash_obj, now_iso, sha256_file
from hydra.ledger.licenses import LicenseRecord, installed_package_licenses


def hm(kind: str, *parts: str) -> str:
    """Stable internal identifiers: hm://model/hydra-router/v7, hm://dataset/router/v19 ..."""
    return "hm://" + "/".join([kind, *[p for p in parts if p]])


class ModelBOM(BaseModel):
    model_id: str
    hm_id: str = ""
    artifact_sha256: str | None = None
    base_models: list[str] = Field(default_factory=list)
    tokenizer: str | None = None
    adapters: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    training_runs: list[str] = Field(default_factory=list)
    training_framework: str | None = None
    merge_operation: dict[str, Any] | None = None
    conversion_tools: list[str] = Field(default_factory=list)
    quantization: dict[str, Any] | None = None
    calibration_dataset: str | None = None
    eval_suites: list[str] = Field(default_factory=list)
    runtime_compatibility: list[str] = Field(default_factory=list)
    software_dependencies: list[str] = Field(default_factory=list)
    licenses: list[LicenseRecord] = Field(default_factory=list)
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    lineage_hash: str = ""
    created_at: str = Field(default_factory=now_iso)


class DataSource(BaseModel):
    id: str
    proportion: float
    rights: str = "proprietary"
    license: str | None = None
    transformations: list[str] = Field(default_factory=list)


class DataBOM(BaseModel):
    dataset_id: str
    hm_id: str = ""
    sources: list[DataSource] = Field(default_factory=list)
    examples: int = 0
    privacy: dict[str, Any] = Field(default_factory=dict)
    dedup: dict[str, Any] = Field(default_factory=dict)
    synthetic_fraction: float = 0.0
    files: dict[str, str] = Field(default_factory=dict)
    corpus_snapshot: str | None = None
    created_at: str = Field(default_factory=now_iso)


def model_bom_from_factory(factory, artifact_id: str) -> ModelBOM:
    """Build an MBOM from the Model Factory store (artifact + lineage chain)."""
    store = factory.store
    art = store.artifacts[artifact_id]
    chain = store.ancestry(artifact_id)
    tools = sorted({lin.operation for lin in chain})
    roots = [store.artifacts[a] for lin in chain for a in lin.parent_ids if a in store.artifacts
             and not store.artifacts[a].parent_id]
    root_art = roots[0] if roots else art
    datasets = sorted({d for lin in chain for d in lin.dataset_ids})
    runs = sorted({lin.training_run for lin in chain if lin.training_run})
    bom = ModelBOM(model_id=art.logical_model, hm_id=hm("artifact", art.format.value, art.id),
                   artifact_sha256=art.fingerprint.weights_sha256 if art.fingerprint else art.checksum,
                   base_models=[root_art.metadata.get("source", root_art.path)],
                   datasets=datasets, training_runs=runs, conversion_tools=tools,
                   quantization={"type": art.quantization} if art.quantization else None,
                   calibration_dataset=art.metadata.get("imatrix"),
                   runtime_compatibility=list(art.runtime_targets),
                   lineage=[lin.model_dump(mode="json") for lin in chain],
                   licenses=[LicenseRecord(artifact_id=art.logical_model, artifact_type="model",
                                           license_id=art.metadata.get("license"))])
    bom.lineage_hash = hash_obj(bom.lineage)
    return bom


def data_bom_from_release(release) -> DataBOM:
    synth = release.synthetic_fraction
    sources = [DataSource(id="hydra-verified-traces", proportion=round(1 - synth, 3), rights="proprietary",
                          license="proprietary", transformations=["privacy_gate", "rights_gate", "dedup", "curation"])]
    if synth:
        sources.append(DataSource(id="hydra-synthetic-foundry", proportion=synth, rights="proprietary",
                                  license="proprietary", transformations=["teacher_ensemble", "verification"]))
    return DataBOM(dataset_id=release.id, hm_id=hm("dataset", release.name, f"v{release.version}"), sources=sources,
                   examples=release.examples, privacy={"pii_scan": "passed", "secrets": "rejected"},
                   dedup={"layers": ["exact", "simhash", "structural", "semantic"],
                          "rejected": release.rejected}, synthetic_fraction=synth, files=release.files,
                   corpus_snapshot=release.corpus_snapshot)


def sbom() -> dict[str, Any]:
    pkgs = installed_package_licenses()
    return {"name": "hydra-engine", "version": hydra.__version__, "generated_at": now_iso(),
            "components": [p.model_dump() for p in pkgs]}


def cyclonedx(*, models: list[ModelBOM] | None = None, datasets: list[DataBOM] | None = None,
              packages: list[LicenseRecord] | None = None, name: str = "hydra-engine") -> dict[str, Any]:
    """CycloneDX 1.6 JSON (SBOM + ML-BOM)."""
    comps: list[dict[str, Any]] = []
    deps: list[dict[str, Any]] = []
    for p in packages or []:
        pname, _, ver = p.artifact_id.removeprefix("pypi:").partition("==")
        comps.append({"type": "library", "bom-ref": p.artifact_id, "name": pname, "version": ver,
                      "purl": f"pkg:pypi/{pname.lower()}@{ver}",
                      "licenses": [{"license": {"name": p.license_id or "unknown"}}]})
    for d in datasets or []:
        comps.append({"type": "data", "bom-ref": d.hm_id or d.dataset_id, "name": d.dataset_id,
                      "data": [{"type": "dataset", "name": d.dataset_id,
                                "contents": {"attachment": {"content": json.dumps({"examples": d.examples})}},
                                "classification": "proprietary",
                                "governance": {"owners": [{"organization": {"name": "Luis Manuel Cousido Hermida"}}]}}],
                      "hashes": [{"alg": "SHA-256", "content": h} for h in list(d.files.values())[:10]],
                      "properties": [{"name": "hydra:synthetic_fraction", "value": str(d.synthetic_fraction)},
                                     {"name": "hydra:corpus_snapshot", "value": str(d.corpus_snapshot)}]})
    for m in models or []:
        ref = m.hm_id or m.model_id
        comps.append({"type": "machine-learning-model", "bom-ref": ref, "name": m.model_id,
                      "hashes": [{"alg": "SHA-256", "content": m.artifact_sha256}] if m.artifact_sha256 else [],
                      "licenses": [{"license": {"name": lic.license_id or "unknown"}} for lic in m.licenses],
                      "modelCard": {
                          "modelParameters": {
                              "approach": {"type": "supervised"},
                              "datasets": [{"ref": ds} for ds in m.datasets],
                              "task": "text-generation",
                              "architectureFamily": ", ".join(m.base_models)[:200]},
                          "quantitativeAnalysis": {"performanceMetrics": []},
                          "considerations": {"technicalLimitations": ["See HYDRA eval reports"]}},
                      "properties": [{"name": "hydra:lineage_hash", "value": m.lineage_hash},
                                     {"name": "hydra:conversion_tools", "value": ",".join(m.conversion_tools)},
                                     {"name": "hydra:quantization", "value": json.dumps(m.quantization or {})}]})
        deps.append({"ref": ref, "dependsOn": list(m.datasets) + list(m.adapters)})
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": f"urn:uuid:{uuid4()}", "version": 1,
            "metadata": {"timestamp": now_iso(), "component": {"type": "application", "name": name,
                                                               "version": hydra.__version__},
                         "manufacturer": {"name": "Luis Manuel Cousido Hermida"},
                         "licenses": [{"license": {"name": "Proprietary - All rights reserved"}}]},
            "components": comps, "dependencies": deps}


def write_bom_bundle(out_dir: Path, *, models: list[ModelBOM] | None = None, datasets: list[DataBOM] | None = None,
                     include_packages: bool = True) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pkgs = installed_package_licenses() if include_packages else []
    files = {
        "hydra-bom.json": {"models": [m.model_dump(mode="json") for m in models or []],
                           "datasets": [d.model_dump(mode="json") for d in datasets or []]},
        "cyclonedx-mlbom.json": cyclonedx(models=models, datasets=datasets, packages=pkgs),
        "licenses.json": [p.model_dump() for p in pkgs] + [lic.model_dump() for m in models or [] for lic in m.licenses],
        "lineage.json": [x for m in models or [] for x in m.lineage],
    }
    for name, data in files.items():
        (out_dir / name).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    hashes = {n: sha256_file(out_dir / n) for n in files}
    (out_dir / "hashes.sha256").write_text("\n".join(f"{h}  {n}" for n, h in hashes.items()) + "\n", encoding="utf-8")
    return hashes
