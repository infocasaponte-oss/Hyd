# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Verify a private export without extracting files or approving training data."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _safe_name(name):
    parts = name.split("/")
    if (not name or "\\" in name or ":" in name or "\x00" in name
            or name.startswith("/") or any(p in {"", ".", ".."} for p in parts)):
        raise ValueError("unsafe archive path")
    return str(PurePosixPath(name))


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("invalid SHA-256")
    return value.lower()


def verify_bundle(source, expected_sha256=None, manifest_name="MANIFEST.json", max_bytes=512 * 1024 * 1024):
    """Require complete manifest coverage. Returned report contains no row content.

    Manifest files may be a path -> hash/object mapping or a list of
    {path, sha256} objects. The manifest cannot hash itself; it is bound by
    the independently supplied archive hash. Integrity is not human approval.
    """
    source = Path(source)
    with source.open("rb") as stream:
        archive_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected_sha256 is not None and archive_hash != _digest(expected_sha256):
        raise ValueError("archive SHA-256 mismatch")
    manifest_name = _safe_name(manifest_name)
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > max_bytes:
            raise ValueError("archive exceeds verification budget")
        files = {}
        all_names = set()
        for info in infos:
            name = _safe_name(info.filename[:-1] if info.is_dir() else info.filename)
            if name in all_names:
                raise ValueError("duplicate archive path")
            all_names.add(name)
            if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise ValueError("symlink or encrypted archive entry")
            if not info.is_dir():
                files[name] = info
        if manifest_name not in files or files[manifest_name].file_size > 8 * 1024 * 1024:
            raise ValueError("missing or oversized manifest")
        manifest = json.loads(archive.read(manifest_name).decode("utf-8-sig"), object_pairs_hook=_unique_object)
        entries = manifest.get("files") if isinstance(manifest, dict) else None
        if isinstance(entries, dict):
            entries = [{"path": p, "sha256": v.get("sha256") if isinstance(v, dict) else v}
                       for p, v in entries.items()]
        if not isinstance(entries, list) or not entries:
            raise ValueError("unsupported or empty manifest files")
        hashes = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("invalid manifest entry")
            name = _safe_name(entry["path"])
            if name in hashes or name == manifest_name:
                raise ValueError("duplicate or self-referential manifest entry")
            hashes[name] = _digest(entry.get("sha256"))
        if set(hashes) != set(files) - {manifest_name}:
            raise ValueError("manifest does not cover archive files exactly")
        for name, expected in hashes.items():
            with archive.open(name) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise ValueError("file SHA-256 mismatch")
    return {"format": "hyd-export-integrity/1", "archive_sha256": archive_hash,
            "archive_hash_bound": expected_sha256 is not None, "verified_files": len(hashes),
            "integrity_verified": True, "training_approved": False,
            "human_annotations_confirmed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--manifest", default="MANIFEST.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-lovable", action="store_true", help="also audit records and annotation references")
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.resolve() == args.archive.resolve():
            raise ValueError("output already exists or would overwrite the source")
        report = verify_bundle(args.archive, args.sha256, args.manifest)
        if args.audit_lovable:
            from hyd_calibrator.lovable_audit import audit_lovable_bundle
            report = audit_lovable_bundle(args.archive, args.sha256)
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, RuntimeError) as error:
        parser.exit(1, f"Export verification failed: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    if report.get("structurally_valid") is False:
        parser.exit(1, "Export has structural errors; report saved, data not approved.\n")


if __name__ == "__main__":
    main()
