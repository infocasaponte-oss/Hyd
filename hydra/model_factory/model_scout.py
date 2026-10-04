# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from hydra.model_factory.gguf_inspection import GGUFError, inspect_gguf


@dataclass(frozen=True)
class ModelArtifact:
    name: str
    path: str
    size_bytes: int
    sha256: str
    gguf_valid: bool = False
    gguf_version: int | None = None
    tensor_count: int | None = None
    architecture: str | None = None
    model_name: str | None = None
    context_length: int | None = None
    embedding_length: int | None = None
    block_count: int | None = None
    file_type: int | None = None
    quantization_version: int | None = None
    metadata_error: str | None = None
    runtime_eligible: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class HashCache:
    """SHA-256 of model files keyed by (path, size, mtime_ns), optionally persisted as JSON.

    Inventory listings hash multi-GB GGUF files; without a cache every request re-read tens of
    gigabytes. Deployment validation never uses the cache (it must read the bytes it promotes)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        if path is not None and path.is_file():
            try:
                self._entries = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._entries = {}

    def sha256(self, file: Path) -> str:
        stat = file.stat()
        key = str(file)
        entry = self._entries.get(key)
        if entry and entry.get("size") == stat.st_size and entry.get("mtime_ns") == stat.st_mtime_ns:
            return entry["sha256"]
        digest = _sha256(file)
        with self._lock:
            self._entries[key] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
            self._save()
        return digest

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(self._entries, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # the cache is an optimisation; hashing still answers correctly without it


def inspect_model_artifact(
    models_root: str | Path,
    artifact_path: str | Path,
    hash_cache: HashCache | None = None,
) -> ModelArtifact:
    # realpath + prefix check (absolute paths are accepted only inside the root, as before).
    root_real = os.path.realpath(models_root)
    candidate = os.path.realpath(os.path.join(root_real, os.fspath(artifact_path)))
    if candidate == root_real or not candidate.startswith(root_real + os.sep):
        raise ValueError("Model artifact path escapes configured models root")
    root = Path(root_real)
    resolved = Path(candidate)
    if not resolved.is_file():
        raise FileNotFoundError(f"Model artifact not found: {artifact_path}")
    if resolved.suffix.lower() != ".gguf":
        raise ValueError("Model artifact must be a GGUF file")

    metadata = None
    metadata_error = None
    try:
        metadata = inspect_gguf(resolved)
    except (GGUFError, OSError) as exc:
        metadata_error = str(exc)

    runtime_eligible = bool(
        metadata
        and metadata.tensor_count > 0
        and metadata.architecture
        and metadata.context_length
        and metadata.context_length > 0
        and metadata.embedding_length
        and metadata.embedding_length > 0
        and metadata.block_count
        and metadata.block_count > 0
    )

    return ModelArtifact(
        name=resolved.name,
        path=str(resolved.relative_to(root)),
        size_bytes=resolved.stat().st_size,
        sha256=hash_cache.sha256(resolved) if hash_cache is not None else _sha256(resolved),
        gguf_valid=metadata is not None,
        gguf_version=metadata.version if metadata else None,
        tensor_count=metadata.tensor_count if metadata else None,
        architecture=metadata.architecture if metadata else None,
        model_name=metadata.model_name if metadata else None,
        context_length=metadata.context_length if metadata else None,
        embedding_length=metadata.embedding_length if metadata else None,
        block_count=metadata.block_count if metadata else None,
        file_type=metadata.file_type if metadata else None,
        quantization_version=(
            metadata.quantization_version if metadata else None
        ),
        metadata_error=metadata_error,
        runtime_eligible=runtime_eligible,
    )


def scan_models(models_root: str | Path, hash_cache: HashCache | None = None) -> list[ModelArtifact]:
    root = Path(models_root).resolve()
    if not root.exists():
        return []
    artifacts = []
    for path in sorted(root.rglob("*.gguf")):
        try:
            artifact = inspect_model_artifact(root, path, hash_cache)
        except (FileNotFoundError, ValueError):
            continue
        artifacts.append(artifact)
    return artifacts
