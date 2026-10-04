"""Validate E2 inputs before importing or downloading an encoder."""
import hashlib
import json
import re

from .admission import require_consent_and_rights
from .annotations import validate_annotations
from .contract import CRITERIA


def admit_dataset(directory, revision, *, require_development=False):
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("encoder revision must be an immutable 40-character commit SHA")
    result, hashes = {}, {}
    seen = {field: {} for field in ("text", "person_id", "family_id", "group_id")}
    splits = ("train", "development", "calibration", "test") if require_development else ("train", "calibration", "test")
    for split in splits:
        path = directory / f"{split}.jsonl"
        raw = path.read_bytes()
        rows = []
        for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{split}:{number}: expected object")
            require_consent_and_rights(row)
            if not isinstance(row.get("input"), dict) or not isinstance(row.get("output"), dict):
                raise ValueError(f"{split}:{number}: input/output objects required")
            text = row.get("input", {}).get("query")
            label = row.get("output", {}).get("task_type")
            if not isinstance(text, str) or not text.strip() or not isinstance(label, str) or label not in CRITERIA:
                raise ValueError(f"{split}:{number}: invalid text or label")
            if row.get("split") != split or row.get("training_allowed") is not (split == "train"):
                raise ValueError(f"{split}:{number}: invalid split permissions")
            meta = row.get("meta", {})
            if not isinstance(meta, dict) or meta.get("real") is not True or meta.get("suspect_template") is not False:
                raise ValueError(f"{split}:{number}: explicit source declarations required")
            values = {"text": " ".join(text.casefold().split()), "group_id": row.get("group_id"),
                      "person_id": meta.get("person_id"), "family_id": meta.get("family_id")}
            for field, value in values.items():
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{split}:{number}: {field} required")
                previous = seen[field].get(value)
                if previous is not None and (previous != split or field == "text"):
                    raise ValueError(f"{split}:{number}: overlapping or duplicate {field}")
                seen[field][value] = split
            if "annotations" in row:
                validate_annotations(row["annotations"], text)
            rows.append(row)
        if not rows or {row["output"]["task_type"] for row in rows} != set(CRITERIA):
            raise ValueError(f"{split}: all ten classes required")
        result[split] = rows
        hashes[split] = hashlib.sha256(raw).hexdigest()
    return result, hashes
