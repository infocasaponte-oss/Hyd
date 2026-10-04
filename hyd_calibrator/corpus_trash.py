# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Recoverable cleanup of byte-identical finalized downloads, independent of cloud services."""
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .atomic import write_text_atomic


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def confined(root, relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(p in ("..", ".trash") for p in path.parts):
        raise ValueError("unsafe corpus path")
    target = root / path
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink() or part.is_junction():
            raise ValueError("linked corpus path")
    if not target.resolve().is_relative_to(root):
        raise ValueError("corpus path escapes root")
    return target


def save(path, data):
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))


@contextmanager
def locked(root):
    trash = root / ".trash"
    if trash.is_symlink() or trash.is_junction():
        raise ValueError("linked trash directory")
    trash.mkdir(exist_ok=True)
    lock = trash / "operation.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        yield trash
    finally:
        os.close(fd)
        lock.unlink()


def plan_duplicates(root, out):
    root = Path(root).resolve(strict=True)
    out = Path(out)
    if out.exists():
        raise ValueError("output already exists")
    seen, entries = {}, []
    files = sorted(p for p in root.rglob("*.jsonl.gz")
                   if not any(part.startswith(".") or part.startswith("_") for part in p.relative_to(root).parts))
    for path in files:
        path = confined(root, path.relative_to(root))
        if not path.is_file():
            continue
        key = (path.stat().st_size, digest(path))
        relative = path.relative_to(root).as_posix()
        if key in seen:
            entries.append({"path": relative, "retained": seen[key], "bytes": key[0],
                            "sha256": key[1], "reason": "byte-identical-copy"})
        else:
            seen[key] = relative
    result = {"format": "hyd-corpus-trash-plan/1", "root": str(root), "entries": entries,
              "scanned_files": len(files), "reclaimable_bytes": sum(e["bytes"] for e in entries)}
    save(out, result)
    return result


def verified(root, entry, field):
    path = confined(root, entry[field])
    if not path.is_file() or path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
        raise ValueError(f"changed or missing {field} file")
    return path


def stage(root, plan):
    root = Path(root).resolve(strict=True)
    data = json.loads(Path(plan).read_text(encoding="utf-8"))
    if data.get("format") != "hyd-corpus-trash-plan/1" or Path(data["root"]).resolve() != root:
        raise ValueError("trash plan root or format mismatch")
    entries = data["entries"]
    for entry in entries:
        for field in ("path", "retained"):
            path = Path(entry[field])
            if not path.name.endswith(".jsonl.gz") or any(p.startswith((".", "_")) for p in path.parts):
                raise ValueError("only finalized corpus files can enter trash")
    paths = {e["path"] for e in entries}
    if len(paths) != len(entries) or any(e["retained"] in paths or e["reason"] != "byte-identical-copy" for e in entries):
        raise ValueError("retained copies must remain outside the trash plan")
    with locked(root) as trash:
        for entry in entries:
            verified(root, entry, "path")
            verified(root, entry, "retained")
        batch_id = str(uuid4())
        batch = trash / batch_id
        batch.mkdir()
        manifest = {**data, "format": "hyd-corpus-trash-batch/1", "batch": batch_id,
                    "state": "staging", "entries": [{**e, "state": "pending"} for e in entries]}
        save(batch / "manifest.json", manifest)
        for number, entry in enumerate(manifest["entries"]):
            source = verified(root, entry, "path")
            verified(root, entry, "retained")
            source.rename(batch / str(number))
            entry["state"] = "trashed"
            save(batch / "manifest.json", manifest)
        manifest["state"] = "trashed"
        save(batch / "manifest.json", manifest)
    return manifest


def finish(root, batch_id, *, purge=False):
    root = Path(root).resolve(strict=True)
    from uuid import UUID
    if str(UUID(batch_id)) != batch_id:
        raise ValueError("invalid batch identifier")
    with locked(root) as trash:
        batch = trash / batch_id
        if batch.is_symlink() or batch.is_junction():
            raise ValueError("linked trash batch")
        manifest_path = batch / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("linked trash manifest")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("format") != "hyd-corpus-trash-batch/1" or data["batch"] != batch_id or Path(data["root"]).resolve() != root:
            raise ValueError("invalid trash manifest")
        operations = []
        for number, entry in enumerate(data["entries"]):
            stored = batch / str(number)
            if not stored.exists() and entry["state"] in ("pending", "restored", "purged"):
                continue
            if stored.is_symlink() or not stored.is_file() or digest(stored) != entry["sha256"]:
                raise ValueError("changed trash file")
            target = confined(root, entry["path"])
            if purge:
                verified(root, entry, "retained")
            elif target.exists():
                raise ValueError("restore would overwrite an existing file")
            operations.append((stored, target, entry))
        for stored, target, entry in operations:
            if purge:
                verified(root, entry, "retained")
                stored.unlink()
                entry["state"] = "purged"
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                stored.rename(target)
                entry["state"] = "restored"
            save(manifest_path, data)
        data["state"] = "purged" if purge else "restored"
        save(manifest_path, data)
    return data
