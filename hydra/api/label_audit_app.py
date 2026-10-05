# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Loopback-only human correction workspace; original corpus stays immutable."""
import argparse
import contextlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from hydra.router.decision_contract import CRITERIA
from hydra.training.decision_active_learning import read_rows
from hydra.training.decision_candidates import file_sha


class Review(BaseModel):
    case_id: str = Field(min_length=1, max_length=200)
    human_label: str = Field(min_length=1, max_length=50)
    reviewer: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=2000)


def create_app(root: Path):
    root = Path(root)
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "hyd-label-review/1":
        raise ValueError("human label review bundle required")
    queue = root / "review-blind.jsonl"
    digest = manifest["files"][queue.name]
    if file_sha(queue) != digest:
        raise ValueError("review queue changed")
    cases = read_rows(queue)
    by_id = {r["id"]: r for r in cases}
    database = root / "human-reviews.sqlite3"
    with contextlib.closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS binding (digest TEXT NOT NULL)")
        existing = db.execute("SELECT digest FROM binding").fetchall()
        if existing and existing != [(digest,)]:
            raise ValueError("reviews belong to another queue")
        if not existing:
            db.execute("INSERT INTO binding VALUES (?)", (digest,))
        db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, payload TEXT NOT NULL)")
        db.commit()
    app, token = FastAPI(), secrets.token_hex(32)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return Response(status_code=403)
        if request.method == "POST" and not secrets.compare_digest(request.headers.get("x-review-token", ""), token):
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'nonce-{token}'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get("/", response_class=HTMLResponse)
    def page():
        return HTMLResponse(Path(__file__).with_name("label_audit_review.html").read_text(encoding="utf-8").replace("REVIEW_NONCE", token))

    def events():
        with contextlib.closing(sqlite3.connect(database)) as db:
            return [json.loads(payload) for payload, in db.execute("SELECT payload FROM events ORDER BY seq")]

    @app.get("/api/cases")
    def data():
        return {"cases": cases, "reviews": {e["id"]: e for e in events()}, "labels": list(CRITERIA) + ["ambiguous"],
                "priority_rows": manifest["priority_rows"]}

    @app.post("/api/review")
    def save(body: Review):
        if body.case_id not in by_id or body.human_label not in (*CRITERIA, "ambiguous") or not body.reviewer.strip():
            raise HTTPException(422, "Escolle unha etiqueta e escribe quen revisa.")
        if body.human_label == "ambiguous" and not body.notes.strip():
            raise HTTPException(422, "Explica por que precisa aclaración.")
        if file_sha(queue) != digest:
            raise HTTPException(409, "A cola cambiou; non se gardou a revisión.")
        original = by_id[body.case_id]
        event = {**original, "human_label": body.human_label, "reviewer": body.reviewer.strip(),
                 "notes": body.notes, "confirmed": True, "training_allowed": False,
                 "reviewed_at": datetime.now(UTC).isoformat(), "source_sha256": manifest["source_sha256"]}
        with contextlib.closing(sqlite3.connect(database)) as db:
            db.execute("INSERT INTO events(id,payload) VALUES (?,?)", (body.case_id, json.dumps(event, ensure_ascii=False)))
            db.commit()
        return {"saved": True, "review": event}

    @app.get("/api/export")
    def export():
        return Response("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events()),
                        media_type="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="hyd-human-review-events.jsonl"'})

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    uvicorn.run(create_app(args.root), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
