"""Freeze reviewed acquisition inventory into an unapproved, deduplicated snapshot."""
import gzip
import hashlib
import io
import json
import re
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

from .atomic import write_text_atomic


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_acquisition(root, inventory, out):
    root, inventory, out = Path(root).resolve(), Path(inventory).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError("snapshot directory already exists")
    if out.is_relative_to(root) or root.is_relative_to(out):
        raise ValueError("choose an output directory separate from acquisition")
    raw = inventory.read_bytes()
    audit = json.loads(raw)
    if not isinstance(audit, dict) or audit.get("format") != "acquisition-source-review/1":
        raise ValueError("reviewed acquisition inventory required")
    files = audit.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("nonempty inventoried file list required")
    inputs, paths = [], set()
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("invalid inventoried path")
        path = (root / entry["path"]).resolve()
        digest = entry.get("sha256")
        if (not path.is_relative_to(root) or path in paths or not path.name.endswith(".jsonl.gz")
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("unsafe or duplicate inventoried path/hash")
        if file_hash(path) != digest:
            raise ValueError(f"acquisition file changed since inventory: {entry['path']}")
        paths.add(path)
        inputs.append((path, entry))
    # No output exists until every input passes the recorded hash check.
    out.mkdir(parents=True, exist_ok=False)
    names = ("candidates", "duplicates", "review")
    counts = dict.fromkeys(names, 0)
    reasons, seen = {}, {}
    with ExitStack() as stack:
        writers = {}
        for name in names:
            binary = stack.enter_context((out / f"{name}.jsonl.gz").open("wb"))
            compressed = stack.enter_context(gzip.GzipFile(filename="", mode="wb", fileobj=binary, mtime=0, compresslevel=1))
            writers[name] = stack.enter_context(io.TextIOWrapper(compressed, encoding="utf-8", newline="\n"))
        for path, entry in inputs:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                        raise ValueError(f"invalid acquired record: {entry['path']}:{number}")
                    text = row["text"]
                    normalized_hash = hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()
                    reference = {"source_file": entry["path"], "source_line": number,
                                 "source_file_sha256": entry["sha256"]}
                    review = []
                    if not text.strip():
                        review.append("empty_text")
                    if "\ufffd" in text:
                        review.append("replacement_characters")
                    license_name = row.get("license")
                    if not isinstance(license_name, str) or not license_name.strip():
                        review.append("missing_license_declaration")
                    elif license_name.strip().casefold() in ("cc-by", "ccby", "cc by"):
                        review.append("unversioned_license_declaration")
                    for field in ("source", "source_revision", "language", "category"):
                        if not isinstance(row.get(field), str) or not row[field].strip():
                            review.append(f"missing_{field}")
                    if not isinstance(row.get("url"), str) or not row["url"].strip():
                        review.append("missing_origin_url")
                    else:
                        try:
                            origin = urlsplit(row["url"])
                            valid_origin = (origin.scheme in ("http", "https") and origin.hostname
                                            and not origin.username and not origin.password)
                        except ValueError:
                            valid_origin = False
                        if not valid_origin:
                            review.append("invalid_origin_url")
                        elif re.search(r"(?:CELEX:|uri=)(?:None|null|undefined)(?:$|[&#])", row["url"], re.I):
                            review.append("placeholder_origin_identifier")
                    if review:
                        bucket = "review"
                    elif normalized_hash in seen:
                        bucket = "duplicates"
                    else:
                        bucket = "candidates"
                    wrapper = {"format": "hyd-acquisition-candidate/1", "original": row,
                               "provenance": reference, "normalized_text_sha256": normalized_hash,
                               "verbatim_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                               "training_allowed": False, "review_status": "pending",
                               "review_reasons": review, "bucket": bucket}
                    if normalized_hash in seen:
                        wrapper["duplicate_of"] = seen[normalized_hash]
                    # A quarantined occurrence never prevents a later complete candidate.
                    if bucket == "candidates":
                        seen[normalized_hash] = reference
                    for reason in review:
                        reasons[reason] = reasons.get(reason, 0) + 1
                    writers[bucket].write(json.dumps(wrapper, ensure_ascii=False, allow_nan=False) + "\n")
                    counts[bucket] += 1
    for path, entry in inputs:
        if file_hash(path) != entry["sha256"]:
            raise ValueError("input changed during snapshot; partial output is not complete")
    report = {"format": "hyd-acquisition-snapshot/1", "complete": True, "training_allowed": False,
              "review_status": "pending", "inventory_sha256": hashlib.sha256(raw).hexdigest(),
              "counts": counts, "review_reasons": reasons, "input_files": files,
              "output_sha256": {name: file_hash(out / f"{name}.jsonl.gz") for name in names},
              "limitations": ["Candidates are not approved for training; license/language labels remain declarations.",
                              "Only normalized text duplicates are detected, not related works or paraphrases.",
                              "Duplicate references point to the first candidate in inventory order."]}
    write_text_atomic(out / "manifest.json", json.dumps(report, ensure_ascii=False, indent=2))
    return report
