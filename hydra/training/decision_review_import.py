# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Version confirmed human corrections without changing original questions or authors."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from hydra.router.decision_contract import CRITERIA
from hydra.training.decision_active_learning import read_rows
from hydra.training.decision_candidates import file_sha
from hydra.training.evidence_io import write_json


def import_reviews(corpus: Path, events: Path, out: Path):
    if out.exists():
        raise FileExistsError("new corpus version directory required")
    originals, reviews = read_rows(corpus), read_rows(events)
    source_sha = file_sha(corpus)
    by_id = {r["id"]: r for r in originals}
    if len(by_id) != len(originals) or not reviews:
        raise ValueError("unique corpus IDs and nonempty review events required")
    latest = {}
    for index, event in enumerate(reviews):
        original = by_id.get(event.get("id"))
        if (not original or event.get("source_sha256") != source_sha
                or event.get("text") != original["text"]
                or event.get("text_sha256") != original["text_sha256"]
                or hashlib.sha256(original["text"].encode()).hexdigest() != original["text_sha256"]
                or event.get("confirmed") is not True
                or not isinstance(event.get("reviewer"), str) or not event["reviewer"].strip()
                or event.get("human_label") not in (*CRITERIA, "ambiguous")
                or event.get("training_allowed") is not False):
            raise ValueError("unconfirmed, altered or incorrectly bound review")
        timestamp = datetime.fromisoformat(event["reviewed_at"])
        if timestamp.tzinfo is None:
            raise ValueError("timezone-aware review timestamp required")
        if event["human_label"] == "ambiguous" and not str(event.get("notes", "")).strip():
            raise ValueError("ambiguous review requires notes")
        key = (timestamp, index)
        if event["id"] not in latest or key > latest[event["id"]][0]:
            latest[event["id"]] = (key, event)
    corrected, changed, unresolved = [], Counter(), 0
    for original in originals:
        row = dict(original)
        if original["id"] in latest:
            event = latest[original["id"]][1]
            label = event["human_label"]
            row["label_review"] = {"previous_expected": original["expected"], "human_label": label,
                                   "reviewer": event["reviewer"], "reviewed_at": event["reviewed_at"],
                                   "notes": event.get("notes", ""), "source_sha256": source_sha}
            if label == "ambiguous":
                unresolved += 1
                row["label_review"]["unresolved"] = True
            else:
                row["expected"] = label
                if label != original["expected"]:
                    changed[original["expected"] + "->" + label] += 1
        corrected.append(row)
    out.mkdir(parents=True)
    target = out / "corpus_reviewed.jsonl"
    target.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in corrected), encoding="utf-8")
    (out / "human-review-events.jsonl").write_bytes(events.read_bytes())
    result = {"format": "hyd-reviewed-corpus/1", "authority": False, "independent_test": False,
              "source_sha256": source_sha, "events_sha256": file_sha(events), "corpus_sha256": file_sha(target),
              "total_rows": len(originals), "review_events": len(reviews), "reviewed_rows": len(latest),
              "changed_rows": sum(changed.values()), "confirmed_unchanged_rows": len(latest) - sum(changed.values()) - unresolved,
              "unresolved_rows": unresolved, "not_reviewed_rows": len(originals) - len(latest),
              "changes": dict(changed), "class_counts_before": dict(Counter(r["expected"] for r in originals)),
              "class_counts_after": dict(Counter(r["expected"] for r in corrected)),
              "originals_modified": False, "question_texts_and_authors_preserved": True,
              "reviewer_identity": "locally declared, not externally authenticated"}
    write_json(out / "MANIFEST.json", result)
    return result


def rescore_rows(predictions, originals, revised):
    """Reuse recorded inference only for identical questions and authors; change targets only."""
    old, new = {r["id"]: r for r in originals}, {r["id"]: r for r in revised}
    if len(old) != len(originals) or len(new) != len(revised) or set(old) != set(new):
        raise ValueError("unchanged unique corpus IDs required")
    if len({r["id"] for r in predictions}) != len(predictions):
        raise ValueError("unique prediction IDs required")
    result = []
    for row in predictions:
        original, corrected = old[row["id"]], new[row["id"]]
        if (any(original[k] != corrected[k] for k in ("text", "text_sha256", "person", "family"))
                or row["text_sha256"] != original["text_sha256"]
                or row["expected"] != original["expected"]
                or row["group_id"] != original["family"]
                or hashlib.sha256(original["text"].encode()).hexdigest() != row["text_sha256"]):
            raise ValueError("recorded inference does not match unchanged original")
        result.append({**row, "expected": corrected["expected"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_reviews(args.corpus, args.events, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
