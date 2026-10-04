"""Exact tokenizer census and source review of a sealed, unapproved acquisition snapshot."""
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import gzip
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .acquisition_snapshot import file_hash
from .atomic import write_text_atomic

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
UNVERSIONED = {"cc-by", "ccby", "cc by"}


def write_report(path, data, *, optional=False):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    for attempt in range(7):
        try:
            write_text_atomic(path, text)
            return
        except PermissionError:
            # Windows readers/antivirus can briefly deny replacing a progress file.
            if attempt == 6:
                if optional:
                    return
                raise
            time.sleep(0.02 * 2 ** attempt)


def source_key(row):
    return json.dumps([row.get("source"), row.get("source_revision"), row.get("license")], ensure_ascii=False)


def signals(row):
    reasons = []
    url = row.get("url")
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        valid_url = bool(parts and parts.scheme in ("http", "https") and parts.hostname
                         and not parts.username and not parts.password)
    except ValueError:
        valid_url = False
    if not valid_url:
        reasons.append("missing_or_invalid_origin_url")
    elif re.search(r"(?:CELEX:|uri=)(?:None|null|undefined)(?:$|[&#])", url, re.I):
        reasons.append("placeholder_origin_identifier")
    license_name = row.get("license")
    if not isinstance(license_name, str) or not license_name.strip():
        reasons.append("missing_license_declaration")
    elif license_name.casefold().strip() in UNVERSIONED:
        reasons.append("unversioned_license_declaration")
    text = row.get("text", "")
    # Search only bounded windows around @, avoiding quadratic scans of long code/data blobs.
    for number, match in enumerate(re.finditer("@", text)):
        if number == 1000:
            reasons.append("email_scan_budget_requires_privacy_review")
            break
        if EMAIL.search(text[max(0, match.start() - 254):match.start() + 254]):
            reasons.append("email_pattern_requires_privacy_review")
            break
    if "\ufffd" in text:
        reasons.append("replacement_characters")
    return reasons


def census(snapshot, tokenizer, out, *, batch_chars=500_000, threads=2, processor=None):
    snapshot, tokenizer, out = Path(snapshot).resolve(), Path(tokenizer).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError("choose a new census directory")
    if batch_chars < 1 or not 1 <= threads <= 4:
        raise ValueError("invalid batch or thread budget")
    manifest_path = snapshot / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("format") != "hyd-acquisition-snapshot/1" or manifest.get("complete") is not True:
        raise ValueError("complete acquisition snapshot required")
    names = ("candidates", "duplicates", "review")
    inputs = {}
    for name in names:
        path = snapshot / f"{name}.jsonl.gz"
        expected = manifest["output_sha256"][name]
        if file_hash(path) != expected:
            raise ValueError("snapshot file hash mismatch")
        inputs[name] = path
    tokenizer_hash = file_hash(tokenizer)
    if processor is None:
        from .bounded_sentencepiece import BoundedSentencePiece
        processor = BoundedSentencePiece(tokenizer)
    if processor.eos_id() < 0 or processor.bos_id() < 0:
        raise ValueError("tokenizer must define BOS and EOS for HYDRA pretraining")
    out.mkdir(parents=True)
    started = time.monotonic()
    totals, groups = {}, {}
    issues = Counter()
    unmeasured_records = []
    token_count_complete = True
    token_conventions = {"content": "SentencePiece encode(original text), no automatic BOS/EOS, no truncation",
                         "pretraining": "content tokens plus BOS and EOS per document, as in base_pretrain._write",
                         "eos_only_scenario": "content tokens plus one EOS per nonempty encoded document; no BOS",
                         "not_applied": "No packing, splits, benchmark decontamination or training admission"}
    token_conventions["memory_bound"] = "Large BPE inputs normalized once; unchanged vocabulary counted in word-aligned spans. No pieces may span word boundaries. Unsupported spans fail closed."

    def persist(complete=False):
        report = {"format": "hyd-corpus-census/1", "complete": complete, "training_allowed": False,
                  "tokenizer_sha256": tokenizer_hash, "tokenizer_vocab_size": processor.vocab_size(),
                  "snapshot_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                  "input_sha256": manifest["output_sha256"], "token_conventions": token_conventions,
                  "token_count_complete": token_count_complete,
                  "unmeasured_records": unmeasured_records,
                  "buckets": totals, "groups": list(groups.values()), "review_signals": dict(issues),
                  "elapsed_seconds": round(time.monotonic() - started, 2),
                  "limitations": ["Languages, categories and licenses are source declarations, not verified findings.",
                                  "Source/language balance measures volume, not semantic quality or topic diversity.",
                                  "Email matching is a review signal; neither proves nor excludes personal data.",
                                  "No robots.txt, TDM opt-out or work-by-work license checks were performed.",
                                  "Downloaded candidates are not content used to train an already released model."]}
        write_report(out / ("report.json" if complete else "progress.json"), report, optional=not complete)
        return report

    for name, path in inputs.items():
        totals[name] = {"rows": 0, "characters": 0, "content_tokens": 0,
                        "tokens_with_eos_only": 0, "pretraining_tokens_with_bos_eos": 0, "unmeasured_rows": 0}
        pending, pending_chars = [], 0

        def flush():
            nonlocal pending, pending_chars, token_count_complete
            if not pending:
                return
            encoded = []
            for row in pending:
                try:
                    encoded.append(processor.encode([row["text"]], out_type=int, num_threads=threads)[0])
                except ValueError as error:
                    if "safe tokenization budget" not in str(error) and "large records require" not in str(error):
                        raise
                    encoded.append(None)
                    token_count_complete = False
                    issues["unmeasured_tokenization_budget_records"] += 1
                    unmeasured_records.append({"bucket": name, "source": row.get("source"),
                                               "verbatim_text_sha256": hashlib.sha256(row["text"].encode()).hexdigest(),
                                               "characters": len(row["text"]), "reason": str(error)})
            if len(encoded) != len(pending):
                raise ValueError("tokenizer result size mismatch")
            for row, ids in zip(pending, encoded, strict=True):
                count = len(ids) if ids is not None else 0
                key = (name, source_key(row), row.get("category"), row.get("language"))
                if key not in groups:
                    groups[key] = {"bucket": name, "source": row.get("source"), "source_revision": row.get("source_revision"),
                                   "license_declaration": row.get("license"), "category_declaration": row.get("category"),
                                   "language_declaration": row.get("language"), "rows": 0, "characters": 0,
                                   "content_tokens": 0, "tokens_with_eos_only": 0, "pretraining_tokens_with_bos_eos": 0,
                                   "unmeasured_rows": 0,
                                   "rights_review": "pending", "training_allowed": False}
                for aggregate in (totals[name], groups[key]):
                    aggregate["rows"] += 1
                    aggregate["characters"] += len(row["text"])
                    aggregate["content_tokens"] += count
                    aggregate["tokens_with_eos_only"] += count + bool(count)
                    aggregate["pretraining_tokens_with_bos_eos"] += count + (2 if ids is not None else 0)
                    aggregate["unmeasured_rows"] += ids is None
                issues.update(signals(row))
            pending, pending_chars = [], 0
            persist()

        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                wrapper = json.loads(line)
                row = wrapper.get("original")
                if (wrapper.get("format") != "hyd-acquisition-candidate/1" or wrapper.get("bucket") != name
                        or not isinstance(row, dict) or not isinstance(row.get("text"), str)):
                    raise ValueError("invalid snapshot record")
                if hashlib.sha256(row["text"].encode()).hexdigest() != wrapper.get("verbatim_text_sha256"):
                    raise ValueError("record text hash mismatch")
                pending.append(row)
                pending_chars += len(row["text"])
                if pending_chars >= batch_chars:
                    flush()
            flush()
        if totals[name]["rows"] != manifest["counts"][name]:
            raise ValueError("snapshot record count mismatch")
    for name, path in inputs.items():
        if file_hash(path) != manifest["output_sha256"][name]:
            raise ValueError("snapshot changed during census")
    if file_hash(tokenizer) != tokenizer_hash or manifest_path.read_bytes() != manifest_bytes:
        raise ValueError("tokenizer or manifest changed during census")
    result = persist(complete=True)
    register = {"format": "hyd-source-rights-review/1", "snapshot_manifest_sha256": result["snapshot_manifest_sha256"],
                "training_allowed": False, "sources": []}
    seen = set()
    for group in groups.values():
        key = (group["source"], group["source_revision"], group["license_declaration"])
        if key in seen:
            continue
        seen.add(key)
        register["sources"].append({"source": key[0], "revision": key[1], "license_declaration": key[2],
                                    "review_status": "pending", "lawful_access": "unknown", "rights_basis": "unknown",
                                    "attribution_complete": "unknown", "tdm_reservations": "unknown",
                                    "personal_data_review": "pending", "evidence": [], "training_allowed": False})
    write_text_atomic(out / "source-rights-review.json", json.dumps(register, ensure_ascii=False, indent=2))
    return result
