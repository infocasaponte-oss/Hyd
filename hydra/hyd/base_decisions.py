# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Turn already-admitted base documents into verifiable extraction decisions.

Unlabelled books are not routing labels. Every generated target here is an exact
substring or count oracle; source licences and work-level splits are preserved.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from hydra.core.atomic import write_text_atomic
from hydra.hyd.stage1 import verify_corpus
from hydra.training.base_corpus import canonical_sha256, file_sha256
from hydra.training.base_data_policy import admit_record


def decisions(document: dict, split: str, work: str, source_hash: str):
    text = document["text"][:320]
    words = sorted(set(re.findall(r"\b[^\W\d_]{4,}\b", text)))
    if len(words) < 3:
        return []
    uid = hashlib.sha256((work + text).encode()).hexdigest()
    quote = words[int(uid[:4], 16) % len(words)]
    absent = "HYD_ABSENT_" + uid[:12]
    if absent in text:
        return []
    common = {"split": split, "family": "document-work:" + hashlib.sha256(work.encode()).hexdigest(),
        "training_allowed": split == "train", "domain": "admitted_document_extraction", "language": "es",
        "rights": {"verified": True, "license": document["license"], "source_manifest_sha256": source_hash},
        "source": {"name": document["source"], "document_id": document["document_id"],
                   "document_sha256": document["sha256"], "excerpt_characters": len(text)}}
    rows = []
    for present, needle in ((True, quote), (False, absent)):
        rows.append({**common, "id": "hyd-document-" + uid[:16] + ("-yes" if present else "-no"),
            "state": {"document": text, "needle": needle},
            "question": {"type": "noul", "instructions": "¿Contiene document la cadena needle exactamente, distinguiendo mayúsculas?"},
            "target": {"false": float(not present), "true": float(present)},
            "oracle": {"operation": "exact_substring", "result": needle in text}})
    count = int(uid[4:6], 16) % 4
    needles = words[:count] + [absent + str(i) for i in range(3 - count)]
    actual = sum(needle in text for needle in needles)
    rows.append({**common, "id": "hyd-document-" + uid[:16] + "-count",
        "state": {"document": text, "needles": needles},
        "question": {"type": "score", "instructions": "Cuenta cuántas cadenas de needles aparecen exactamente en document.",
                     "criteria": ["Ninguna cadena", "Una cadena", "Dos cadenas", "Tres cadenas"]},
        "target": {str(i): float(i == actual) for i in range(4)},
        "oracle": {"operation": "exact_substring_count", "result": actual}})
    return rows


def build(base_corpus: Path, synthetic: Path, out: Path, per_source_split: int = 40):
    if out.exists():
        raise FileExistsError("use a new versioned supervised corpus")
    if not 1 <= per_source_split <= 10000:
        raise ValueError("invalid document quota")
    base_manifest = verify_corpus(base_corpus)
    source_hash = canonical_sha256(base_corpus / "manifest.json")
    synthetic_manifest = json.loads((synthetic / "manifest.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True)
    streams = {split: (out / (split + ".jsonl")).open("w", encoding="utf-8", newline="\n")
               for split in ("train", "calibration", "development", "test")}
    counts, quotas, seen_works, seen_excerpts = Counter(), Counter(), set(), set()
    try:
        for split, stream in streams.items():
            original = synthetic / (split + ".jsonl")
            if file_sha256(original) != synthetic_manifest["files"][original.name]["sha256"]:
                raise ValueError("synthetic corpus checksum mismatch")
            for line in original.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    stream.write(line + "\n")
                    counts[split] += 1
        for parent_split in ("train", "validation"):
            for filename in sorted(base_manifest["files"]):
                if not filename.startswith(parent_split + "-"):
                    continue
                with gzip.open(base_corpus / filename, "rt", encoding="utf-8") as source:
                    for line in source:
                        document = json.loads(line)
                        if not admit_record(document["license"].split(", ")).allowed:
                            raise ValueError("base document no longer passes the admitted license policy")
                        identifier = document["document_id"]
                        if "PleIAs" in document["source"]:
                            identifier = re.sub(r"#\d+$", "", identifier)
                        work = document["source"] + "/" + identifier
                        if work in seen_works:
                            continue
                        seen_works.add(work)
                        bucket = int(hashlib.sha256(work.encode()).hexdigest()[:8], 16) % 10
                        split = "test" if parent_split == "validation" else "train" if bucket < 8 else "calibration" if bucket == 8 else "development"
                        key = document["source"], split
                        if quotas[key] >= per_source_split:
                            continue
                        text_hash = hashlib.sha256(document["text"][:320].encode()).hexdigest()
                        if text_hash in seen_excerpts:
                            continue
                        rows = decisions(document, split, work, source_hash)
                        if not rows:
                            continue
                        seen_excerpts.add(text_hash)
                        for row in rows:
                            streams[split].write(json.dumps(row, ensure_ascii=False) + "\n")
                            counts[split] += 1
                        quotas[key] += 1
    finally:
        for stream in streams.values():
            stream.close()
    manifest = {"format": "hyd-supervised-corpus/3", "parent_base_corpus_sha256": source_hash,
        "parent_base_corpus": str(base_corpus.resolve()), "synthetic_manifest_sha256": file_sha256(synthetic / "manifest.json"),
        "source_work_counts": [{"source": source, "split": split, "works": n} for (source, split), n in quotas.items()],
        "files": {split + ".jsonl": {"sha256": file_sha256(out / (split + ".jsonl")), "records": counts[split]} for split in streams},
        "notice": str((base_corpus / "THIRD_PARTY_DATA_NOTICE.txt").resolve()), "notice_sha256": base_manifest["notice_sha256"],
        "generator_sha256": file_sha256(Path(__file__)), "independent_test": False,
        "limitations": ["Exact extraction oracles are not general reasoning supervision.",
                        "Some unlabelled source documents were already seen during pretraining or perplexity validation.",
                        "Calibration/development/test work families are excluded from supervised training; independent human confirmation still required."]}
    write_text_atomic(out / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest
