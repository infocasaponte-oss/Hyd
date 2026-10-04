"""Streaming, non-destructive audit of a sealed corpus; no source text in reports."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from hydra.core.atomic import write_text_atomic
from hydra.training.base_corpus import canonical_sha256
from hydra.training.base_data_policy import admit_record


def reviewed_warnings(report: dict, path: str | None) -> bool:
    """A review binds the exact immutable report, corpus and observed warning counts."""
    if not path or not Path(path).is_file() or not report["integrity_passed"]:
        return False
    review = json.loads(Path(path).read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return (review.get("format") == "hyd-corpus-review/1" and review.get("status") == "APPROVED"
            and review.get("report_sha256") == digest
            and review.get("corpus_manifest_sha256") == report["corpus_manifest_sha256"]
            and review.get("accepted_warnings") == report["warnings"]
            and bool(review.get("reviewer")) and bool(review.get("rationale"))
            and bool(review.get("evidence")))


def audit(corpus: Path, output: Path) -> dict:
    from hydra.hyd.stage1 import verify_corpus
    manifest = verify_corpus(corpus)
    output.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(output / "index.sqlite")
    failures, warnings, sources = Counter(), Counter(), Counter()
    database.executescript("DROP TABLE IF EXISTS texts; DROP TABLE IF EXISTS works; "
        "CREATE TABLE texts (hash TEXT PRIMARY KEY, split TEXT); "
        "CREATE TABLE works (id TEXT PRIMARY KEY, split TEXT);")
    documents = characters = 0
    try:
        for name in sorted(manifest["files"]):
            split = "validation" if name.startswith("validation-") else "train"
            with gzip.open(corpus / name, "rt", encoding="utf-8") as stream:
                for line in stream:
                    record = json.loads(line)
                    text = record["text"]
                    documents += 1
                    characters += len(text)
                    sources[record["source"] + ":" + split] += 1
                    digest = hashlib.sha256(text.encode()).hexdigest()
                    if digest != record["sha256"]:
                        failures["document_hash_mismatch"] += 1
                    if not text.strip():
                        failures["empty_text"] += 1
                    if not admit_record(record["license"].split(", ")).allowed:
                        failures["unadmitted_license"] += 1
                    previous = database.execute("SELECT split FROM texts WHERE hash=?", (digest,)).fetchone()
                    if previous:
                        failures["cross_split_duplicate" if previous[0] != split else "duplicate_text"] += 1
                    else:
                        database.execute("INSERT INTO texts VALUES (?,?)", (digest, split))
                    # PleIAs chunks use #suffix; retain a source-scoped work identity.
                    identifier = str(record["document_id"])
                    if "PleIAs" in record["source"]:
                        identifier = identifier.split("#", 1)[0]
                    work = record["source"] + ":" + identifier
                    previous = database.execute("SELECT split FROM works WHERE id=?", (work,)).fetchone()
                    if previous and previous[0] != split:
                        failures["work_split_leakage"] += 1
                    elif not previous:
                        database.execute("INSERT INTO works VALUES (?,?)", (work, split))
                    if "\ufffd" in text:
                        warnings["replacement_character_documents"] += 1
                    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
                        warnings["possible_email_documents"] += 1
                    if len(text) > 100 and sum(c.isalpha() for c in text) / len(text) < .25:
                        warnings["low_letter_ratio_documents"] += 1
                    if documents % 10000 == 0:
                        database.commit()
        database.commit()
    finally:
        database.close()
    report = {"format": "hyd-corpus-quality/1", "corpus_manifest_sha256": canonical_sha256(corpus / "manifest.json"),
        "documents": documents, "characters": characters, "source_split_documents": dict(sources),
        "failures": dict(failures), "warnings": dict(warnings), "integrity_passed": not failures,
        "review_required": bool(warnings), "source_modified": False,
        "limitations": ["Heuristic warnings require source-specific review, not automatic deletion.",
                        "No semantic near-duplicate or exhaustive personal-data certification."]}
    write_text_atomic(output / "report.json", json.dumps(report, indent=2, ensure_ascii=False))
    return report
