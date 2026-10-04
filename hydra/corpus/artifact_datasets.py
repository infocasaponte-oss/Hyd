# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.corpus.artifact_candidates import CorpusRecord, CorpusStatus
from hydra.core.runtime_paths import runtime_path


class DatasetManifest(BaseModel):
    dataset_id: UUID = Field(default_factory=uuid4)
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    record_ids: list[UUID]
    record_hashes: list[str]
    manifest_hash: str = ""


class DatasetFactory:
    def __init__(self, root: str | Path = runtime_path("datasets")):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def release(self, name: str, records: list[CorpusRecord]) -> DatasetManifest:
        curated = [r for r in records if r.status == CorpusStatus.CURATED]
        if len(curated) != len(records):
            raise ValueError("Dataset releases may contain only CURATED corpus records")
        hashes = [r.content_hash for r in curated]
        if len(hashes) != len(set(hashes)):
            raise ValueError("Duplicate corpus content in dataset release")
        manifest = DatasetManifest(
            name=name,
            record_ids=[r.record_id for r in curated],
            record_hashes=hashes,
        )
        body = manifest.model_dump(mode="json", exclude={"manifest_hash"})
        manifest.manifest_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        path = self.root / f"{manifest.dataset_id}.manifest.json"
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest
