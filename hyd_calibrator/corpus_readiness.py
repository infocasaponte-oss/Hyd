"""Evidence-bound dataset readiness checks; no automatic legal or training authorization."""
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
import re
from collections import Counter
from pathlib import Path

from .acquisition_snapshot import file_hash
from .atomic import write_text_atomic
from hydra.training.base_data_policy import admit_source


def valid_evidence(evidence, root):
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return False
        relative = Path(item["path"])
        path = root / relative
        unsafe = (relative.is_absolute() or ".." in relative.parts or not relative.parts
                  or not path.resolve().is_relative_to(root)
                  or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p != root))
        digest = item.get("sha256", "")
        if (unsafe or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or not path.is_file() or file_hash(path) != digest):
            return False
    return True


def readiness(census_path, rights_path, evidence_root, out):
    out, evidence_root = Path(out), Path(evidence_root).resolve(strict=True)
    if out.exists():
        raise ValueError("output already exists")
    report = json.loads(Path(census_path).read_text(encoding="utf-8"))
    rights = json.loads(Path(rights_path).read_text(encoding="utf-8"))
    if report.get("format") != "hyd-corpus-census/1" or report.get("complete") is not True:
        raise ValueError("complete tokenizer census required")
    if (rights.get("format") != "hyd-source-rights-review/1"
            or rights.get("snapshot_manifest_sha256") != report["snapshot_manifest_sha256"]):
        raise ValueError("rights review must bind the exact snapshot")
    decisions = {}
    for entry in rights["sources"]:
        key = (entry["source"], entry["revision"], entry["license_declaration"])
        if key in decisions:
            raise ValueError("duplicate source review")
        decisions[key] = entry
    blockers, balances = [], {name: Counter() for name in ("source", "language_declaration", "category_declaration")}
    if report.get("token_count_complete") is not True:
        blockers.append({"scope": "dataset", "reasons": ["unmeasured_records_must_be_resolved"]})
    total_tokens = 0
    for group in report["groups"]:
        if group["bucket"] != "candidates":
            continue
        key = (group["source"], group["source_revision"], group["license_declaration"])
        entry = decisions.get(key, {})
        pending = []
        if not admit_source(key[2]).allowed:
            pending.append("license_declaration_excluded_by_project_policy")
        reviewer = entry.get("reviewer", {})
        if entry.get("review_status") != "reviewed" or reviewer.get("kind") != "human" or not reviewer.get("id"):
            pending.append("human_rights_review_missing")
        for field, accepted in {"lawful_access": {"reviewed"}, "rights_basis": {"explicit-license", "public-domain", "own-work", "tdm-exception-reviewed"},
                                "attribution_complete": {"reviewed", "not-required-reviewed"},
                                "tdm_reservations": {"respected-reviewed", "not-applicable-reviewed"},
                                "personal_data_review": {"reviewed"}}.items():
            if entry.get(field) not in accepted:
                pending.append(f"{field}_pending")
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            pending.append("source_evidence_missing")
        elif not valid_evidence(evidence, evidence_root):
            pending.append("source_evidence_invalid")
        if pending:
            blockers.append({"source": key[0], "revision": key[1], "license_declaration": key[2],
                             "reasons": sorted(set(pending))})
        count = group["content_tokens"]
        total_tokens += count
        for name in balances:
            balances[name][str(group.get(name))] += count
    quality = rights.get("dataset_review", {})
    quality_reviewer = quality.get("reviewer", {})
    if (quality_reviewer.get("kind") != "human" or not quality_reviewer.get("id")
            or not valid_evidence(quality.get("evidence"), evidence_root)):
        blockers.append({"scope": "dataset", "reasons": ["documented_human_dataset_review_missing"]})
    for field in ("diversity_reviewed", "language_verified", "benchmark_decontamination_verified"):
        if quality.get(field) is not True:
            blockers.append({"scope": "dataset", "reasons": [field + "_pending"]})
    if not total_tokens:
        blockers.append({"scope": "dataset", "reasons": ["no_candidate_tokens"]})
    result = {"format": "hyd-corpus-readiness/1", "training_allowed": False,
              "ready_for_dataset_build": not blockers, "blockers": blockers,
              "snapshot_manifest_sha256": report["snapshot_manifest_sha256"],
              "census_sha256": file_hash(Path(census_path)), "rights_review_sha256": file_hash(Path(rights_path)),
              "candidate_content_tokens": total_tokens,
              "token_count_complete": report.get("token_count_complete") is True,
              "candidate_balance_by_tokens": {name: [{"declaration": value, "tokens": count,
                                                        "share": count / total_tokens if total_tokens else None}
                                                       for value, count in counter.most_common()]
                                               for name, counter in balances.items()},
              "limitations": ["Human reviews are declarations bound to files, not a legal certificate.",
                              "This diagnostic does not authorize training or replace existing admission checks.",
                              "Volume balance is not a semantic quality or diversity evaluation.",
                              "When token_count_complete is false, token totals/balances cover measured records only."]}
    write_text_atomic(out, json.dumps(result, ensure_ascii=False, indent=2))
    return result
