# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Small human review UI for the pinned external holdout; no automatic certification."""
import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from hydra.training.evidence_io import write_json
from hydra.training.verified_corpus import sha256

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
# Source checkout -> repository root. Installed package (wheel/Docker) -> working directory, where
# data/, docs/evidence and runtime/ live; never site-packages.
ROOT = _SOURCE_ROOT if (_SOURCE_ROOT / "pyproject.toml").is_file() else Path.cwd()
DATA = ROOT / "data/external-evaluation-v2"
ANSWERS = ROOT / "docs/evidence/external-evaluation-v5.json"
REVIEWS = ROOT / "runtime/external-evaluation-v5-reviews.json"
LOCK = asyncio.Lock()


class Review(BaseModel):
    case_id: int = Field(ge=1,le=1000000)
    decision: Literal["correct", "incorrect", "ambiguous"]
    reviewer: str = Field(min_length=1,max_length=120)
    note: str = Field(default="",max_length=2000)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Authorship(BaseModel):
    source: Literal["human","mixed","ai","unknown"]
    reviewer: str = Field(min_length=1,max_length=120)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def cases():
    if not (DATA/"manifest.json").is_file() or not (DATA/"cases.json").is_file():
        raise HTTPException(404,"El conjunto de evaluación externa no está instalado en este nodo")
    manifest=json.loads((DATA/"manifest.json").read_text(encoding="utf-8"))
    if sha256(DATA/"cases.json") != manifest["cases_sha256"]:
        raise HTTPException(409,"El test congelado ha cambiado")
    return json.loads((DATA/"cases.json").read_text(encoding="utf-8-sig")),manifest


def register(app,secured,candidate_version=5):
    if candidate_version not in (5,6,7,8):
        raise ValueError("unsupported review candidate")
    answers_path=ANSWERS if candidate_version==5 else ROOT/f"docs/evidence/external-evaluation-v{candidate_version}.json"
    reviews_path=REVIEWS if candidate_version==5 else ROOT/f"runtime/external-evaluation-v{candidate_version}-reviews.json"
    @app.get("/hydra/v1/evaluation/review",response_class=HTMLResponse)
    async def page():
        from hydra.api.platform_routes import STUDIO_HEADERS
        return HTMLResponse((Path(__file__).with_name("evaluation_review.html")).read_text(encoding="utf-8"),
                            headers=STUDIO_HEADERS)

    @app.get("/hydra/v1/evaluation/cases",dependencies=secured)
    async def get_cases():
        rows,manifest=cases()
        report=json.loads(answers_path.read_text(encoding="utf-8")) if answers_path.exists() else {}
        saved=json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.exists() else {}
        if report and report.get("dataset_sha256") != manifest["cases_sha256"]:
            raise HTTPException(409,"Las respuestas pertenecen a otro test")
        if saved and saved.get("artifact_sha256") != report.get("artifact_sha256"):
            saved={}
        return dict(cases=rows,answers=report,reviews=saved,manifest=manifest,candidate_version=candidate_version)

    @app.post("/hydra/v1/evaluation/review",dependencies=secured)
    async def save_review(body:Review):
        rows,manifest=cases()
        if body.case_id not in {r["id"] for r in rows} or not answers_path.exists():
            raise HTTPException(409,"Todavía falta la inferencia real de este test")
        report=json.loads(answers_path.read_text(encoding="utf-8"))
        if body.artifact_sha256 != report.get("artifact_sha256") or report.get("dataset_sha256") != manifest["cases_sha256"]:
            raise HTTPException(409,"Modelo o test distintos de los revisados")
        answer=next((a for a in report.get("cases",[]) if a["id"]==body.case_id),None)
        if not answer or "output" not in answer or answer.get("error"):
            raise HTTPException(409,"Este caso no tiene una respuesta real revisable")
        if body.decision=="ambiguous" and not body.note.strip():
            raise HTTPException(422,"Indica qué interpretación o referencia es ambigua")
        if not body.reviewer.strip():
            raise HTTPException(422,"Indica el nombre del revisor")
        async with LOCK:
            saved=json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.exists() else {}
            if saved and saved.get("artifact_sha256") != body.artifact_sha256:
                raise HTTPException(409,"Existen revisiones de otro modelo; no se sobrescriben")
            saved.update(artifact_sha256=body.artifact_sha256,dataset_sha256=manifest["cases_sha256"],approved=False)
            saved.setdefault("cases",{})[str(body.case_id)] = body.model_dump()
            saved["reviewed"]=len(saved["cases"])
            saved["correct"]=sum(c["decision"]=="correct" for c in saved["cases"].values())
            saved["ambiguous"]=sum(c["decision"]=="ambiguous" for c in saved["cases"].values())
            # Every case remains in the denominator: ambiguity cannot silently improve accuracy.
            saved["accuracy_all_cases"]=saved["correct"]/len(rows)
            excluded={i for group in manifest.get("duplicate_groups",[]) for i in group[1:]}
            unique=[r for r in rows if r["id"] not in excluded]
            saved["unique_cases"]=len(unique)
            saved["unique_reviewed"]=sum(str(r["id"]) in saved["cases"] for r in unique)
            saved["unique_correct"]=sum(saved["cases"].get(str(r["id"]),{}).get("decision")=="correct" for r in unique)
            saved["accuracy_unique_cases"]=saved["unique_correct"]/len(unique)
            saved["complete"]=saved["unique_reviewed"]==len(unique)
            write_json(reviews_path,saved)
            return saved

    @app.post("/hydra/v1/evaluation/authorship",dependencies=secured)
    async def authorship(body:Authorship):
        _,manifest=cases()
        if not answers_path.exists() or not body.reviewer.strip():
            raise HTTPException(409,"Faltan respuestas reales o el nombre del revisor")
        report=json.loads(answers_path.read_text(encoding="utf-8"))
        if report.get("artifact_sha256")!=body.artifact_sha256 or report.get("dataset_sha256")!=manifest["cases_sha256"]:
            raise HTTPException(409,"El modelo o el test han cambiado")
        async with LOCK:
            saved=json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.exists() else {}
            if saved and saved.get("artifact_sha256")!=body.artifact_sha256:
                raise HTTPException(409,"No se sobrescriben revisiones de otro modelo")
            saved.update(artifact_sha256=body.artifact_sha256,dataset_sha256=manifest["cases_sha256"],approved=False,
                         source_authorship=body.source,human_authorship_attested=body.source=="human",
                         authorship_attestation_reviewer=body.reviewer)
            write_json(reviews_path,saved)
            return saved
