"""Recover explicit preserved origin links without rewriting acquired text or rights."""
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import gzip
import hashlib
import json
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from .acquisition_snapshot import file_hash
from .atomic import write_text_atomic


def recover_link(row):
    if row.get("url"):
        return None
    source = row.get("source")
    if source not in ("PleIAs/YouTube-Commons", "PleIAs/common_corpus"):
        return None
    value = row.get("video_link" if source == "PleIAs/YouTube-Commons" else "id")
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            return None
        if source == "PleIAs/YouTube-Commons" and (parts.scheme != "https" or parts.hostname not in ("youtube.com", "www.youtube.com", "youtu.be")):
            return None
        host = parts.hostname.lower()
        if "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
    except ValueError:
        return None
    return value


def build_overlay(snapshot, out):
    snapshot, out = Path(snapshot).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError("choose a new overlay directory")
    raw = (snapshot / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    if manifest.get("format") != "hyd-acquisition-snapshot/1" or manifest.get("complete") is not True:
        raise ValueError("complete snapshot required")
    source = snapshot / "review.jsonl.gz"
    expected = manifest["output_sha256"]["review"]
    if file_hash(source) != expected:
        raise ValueError("snapshot hash mismatch")
    out.mkdir(parents=True)
    count, by_field = 0, {}
    with gzip.open(source, "rt", encoding="utf-8") as stream, (out / "origin-overlay.jsonl").open("w", encoding="utf-8") as target:
        for line in stream:
            wrapper = json.loads(line)
            row = wrapper["original"]
            link = recover_link(row)
            if link is None:
                continue
            digest = hashlib.sha256(row["text"].encode()).hexdigest()
            if digest != wrapper["verbatim_text_sha256"]:
                raise ValueError("text hash mismatch")
            field = "original.video_link" if row["source"] == "PleIAs/YouTube-Commons" else "original.id"
            entry = {"format": "hyd-origin-overlay/1", "provenance": wrapper["provenance"],
                     "verbatim_text_sha256": digest, "origin_url": link,
                     "derived_from": field, "locator_semantics": "declared-video-link" if field.endswith("video_link") else "identifier-url-requires-origin-review",
                     "review_status": "pending",
                     "training_allowed": False}
            target.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1
            by_field[field] = by_field.get(field, 0) + 1
    if file_hash(source) != expected or (snapshot / "manifest.json").read_bytes() != raw:
        raise ValueError("snapshot changed during overlay")
    result = {"format": "hyd-origin-overlay-manifest/1", "complete": True, "rows": count, "by_field": by_field,
              "training_allowed": False, "snapshot_manifest_sha256": hashlib.sha256(raw).hexdigest(),
              "input_sha256": expected, "output_sha256": file_hash(out / "origin-overlay.jsonl"),
              "limitations": ["Only explicit preserved video_link or Common Corpus identifier URLs are recovered.",
                              "An identifier URL is a locator candidate, not a verified original-work URL.",
                              "No URLs, authorship, consent, license versions or rights decisions are invented.",
                              "Overlay requires review; original bucket assignment and text are unchanged."]}
    write_text_atomic(out / "manifest.json", json.dumps(result, indent=2))
    return result
