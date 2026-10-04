# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Non-destructive evaluation deduplication and acquisition source accounting."""
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from .atomic import write_text_atomic


def deduplicate_evaluation(source, out, *, text_field, reference_field, evaluation_kind, review_only=False):
    source, out = Path(source), Path(out)
    if out.exists():
        raise ValueError("output already exists; choose a new review snapshot")
    if evaluation_kind not in ("general-response", "hyd-routing"):
        raise ValueError("explicit evaluation kind required")
    raw = source.read_bytes()
    if source.suffix == ".jsonl":
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    else:
        rows = json.loads(raw)
    if not isinstance(rows, list) or not rows:
        raise ValueError("nonempty evaluation list required")
    unique, groups, conflicting = [], {}, set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get(text_field), str) or not row[text_field].strip():
            raise ValueError(f"row {index + 1}: original question required")
        if reference_field not in row:
            raise ValueError(f"row {index + 1}: reference required")
        key = " ".join(row[text_field].casefold().split())
        group = groups.setdefault(key, [])
        if group and rows[group[0]][reference_field] != row[reference_field]:
            conflicting.add(key)
        if not group:
            unique.append(row)
        group.append(index)
    if conflicting and not review_only:
        raise ValueError("conflicting references for normalized duplicate; use --review-only for inspection")
    report = {"format": "evaluation-dedup-review/1", "evaluation_kind": evaluation_kind,
              "source_sha256": hashlib.sha256(raw).hexdigest(), "rows": len(rows), "unique": len(unique),
              "duplicate_groups": [indices for indices in groups.values() if len(indices) > 1],
              "conflicting_reference_groups": [groups[key] for key in sorted(conflicting)],
              "replacement_character_rows": [index for index, row in enumerate(rows)
                                             if "\ufffd" in row[text_field] or "\ufffd" in json.dumps(row[reference_field], ensure_ascii=False)],
              "deduplicated_ready": not conflicting and not review_only,
              "index_basis": "zero-based source row position", "review_status": "pending",
              "independence_verified": False, "accuracy_measured": False, "training_allowed": False}
    out.mkdir(parents=True, exist_ok=False)
    write_text_atomic(out / "original.json", json.dumps(rows, ensure_ascii=False, indent=2))
    if not conflicting and not review_only:
        write_text_atomic(out / "deduplicated.json", json.dumps(unique, ensure_ascii=False, indent=2))
        report["deduplicated_sha256"] = hashlib.sha256((out / "deduplicated.json").read_bytes()).hexdigest()
    write_text_atomic(out / "manifest.json", json.dumps(report, indent=2))
    return report


def acquisition_report(root, out):
    root, out = Path(root), Path(out)
    if out.exists():
        raise ValueError("output already exists")
    groups, seen, files = {}, set(), []
    for path in sorted(root.rglob("*.jsonl.gz")):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": digest.hexdigest()})
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                    raise ValueError(f"invalid text in {path.name}")
                key = tuple(row.get(field, "unknown") for field in ("category", "source", "license", "language"))
                if any(not isinstance(value, str) for value in key):
                    raise ValueError("invalid source metadata")
                count = groups.setdefault(key, Counter())
                text = row["text"]
                text_hash = hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()
                count["rows"] += 1
                count["characters"] += len(text)
                count["empty"] += not bool(text.strip())
                count["replacement_character_rows"] += "\ufffd" in text
                count["normalized_duplicates"] += text_hash in seen
                seen.add(text_hash)
    if not files:
        raise ValueError("no acquisition jsonl.gz files found")
    report = {"format": "acquisition-source-review/1", "snapshot_transactional": False,
              "training_admission": False, "tokens_measured": False, "download_bytes_measured": False,
              "files": files, "groups": [{**dict(zip(("category", "source", "license", "language"), key)),
                                            **dict(count)} for key, count in groups.items()],
              "limitations": ["Duplicate count is diagnostic and depends on sorted file order.",
                              "Source labels are declarations, not verification of licence, language or domain.",
                              "No tokens, quality scores or transfer costs are inferred from characters."]}
    write_text_atomic(out, json.dumps(report, ensure_ascii=False, indent=2))
    return report
