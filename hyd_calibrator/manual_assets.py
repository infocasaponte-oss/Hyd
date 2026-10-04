"""Import an explicitly selected local folder of books, preserving bytes and pending reviews."""
import hashlib
import json
import uuid
from pathlib import Path

from .acquisition_snapshot import file_hash
from .atomic import write_text_atomic

EXTENSIONS = {".pdf", ".epub", ".txt", ".html", ".htm", ".md", ".mobi"}
SOURCES = {"unknown", "elejandria", "textos-info", "openlibrary", "cervantes", "gutenberg"}


def import_assets(input_dir, out, source="unknown", max_file_bytes=200 * 1024 * 1024):
    root, out = Path(input_dir).resolve(strict=True), Path(out).resolve()
    if source not in SOURCES or not root.is_dir() or out.exists():
        raise ValueError("valid source/input directory and new output required")
    if out.is_relative_to(root) or root.is_relative_to(out):
        raise ValueError("output must be separate from input")
    files = sorted(root.iterdir())
    if not files or len(files) > 100:
        raise ValueError("select a dedicated folder containing 1 to 100 files")
    for path in files:
        if path.is_symlink() or path.is_junction() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError("only supported regular book files; no folders, links or executable archives")
        if not 0 < path.stat().st_size <= max_file_bytes:
            raise ValueError("empty file or file exceeds import budget")
    out.mkdir()
    records = []
    for path in files:
        identifier = str(uuid.uuid4())
        folder = out / identifier
        folder.mkdir()
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as original, (folder / "asset.raw").open("xb") as target:
            while chunk := original.read(1024 * 1024):
                size += len(chunk)
                if size > max_file_bytes:
                    raise ValueError("file grew beyond import budget")
                digest.update(chunk)
                target.write(chunk)
        if file_hash(path) != digest.hexdigest():
            raise ValueError("source changed while importing; incomplete output")
        record = {"format": "hyd-manual-asset/1", "id": identifier, "state": "raw-pending-review", "complete": True,
                  "original_filename": path.name, "extension": path.suffix.lower(), "bytes": size,
                  "sha256": digest.hexdigest(), "source_id": source, "source_context_url_declared": None,
                  "rights_review": "pending", "privacy_review": "pending", "decontamination": "pending",
                  "training_allowed": False, "extraction_performed": False}
        write_text_atomic(folder / "manifest.json", json.dumps(record, ensure_ascii=False, indent=2))
        records.append(record)
    result = {"format": "hyd-manual-asset-inventory/1", "complete": True,
              "training_allowed": False, "files": records}
    write_text_atomic(out / "manifest.json", json.dumps(result, ensure_ascii=False, indent=2))
    return result
