"""E3 observation metrics against explicitly selected human annotation events."""
from .annotations import validate_annotations


def evaluate_e3(rows, predictions, selections):
    """All inputs keyed by SHA-256 of the verbatim text; no latest-event inference."""
    import hashlib

    if not isinstance(rows, list) or not isinstance(predictions, dict) or not isinstance(selections, dict):
        raise ValueError("E3 requires rows and explicit prediction/selection maps")
    if any(not isinstance(key, str) or not isinstance(value, str) or not value for key, value in selections.items()):
        raise ValueError("invalid selected event identifiers")
    seen, observations = set(), []
    excluded = {"unselected": 0, "pending": 0, "unknown_risk": 0, "unknown_context": 0}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError("E3 requires original nonempty text")
        text = row["text"]
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in seen:
            raise ValueError("duplicate text in E3 evaluation")
        seen.add(key)
        events = validate_annotations(row.get("annotations", []), text)
        selected = selections.get(key)
        if selected is None:
            excluded["unselected"] += 1
            continue
        event = next((event for event in events if event["event_id"] == selected), None)
        if event is None:
            raise ValueError("selected annotation not found for original text")
        if event["status"] != "reviewed":
            excluded["pending"] += 1
            continue
        prediction = predictions.get(key)
        if not isinstance(prediction, dict) or set(prediction) != {"dangerous", "missing_context"}:
            raise ValueError("explicit E3 risk/context prediction required for selected event")
        if any(type(value) is not bool for value in prediction.values()):
            raise ValueError("E3 predictions must be literal booleans")
        observations.append((event, prediction))
    if set(selections) - seen or set(predictions) - seen:
        raise ValueError("E3 input references unknown questions")

    def metrics(subset, kind):
        counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "unknown": 0}
        for event, prediction in subset:
            field = "risk_kind" if kind == "dangerous" else "context_status"
            value = event[field]
            if value == "unknown":
                counts["unknown"] += 1
                continue
            # Security/privacy/high_risk are different categories, not benign negatives.
            if kind == "dangerous" and value not in ("dangerous", "benign"):
                counts["unknown"] += 1
                continue
            truth = value == ("dangerous" if kind == "dangerous" else "missing")
            counts["tp" if truth and prediction[kind] else "fn" if truth else "fp" if prediction[kind] else "tn"] += 1
        tp, fp, fn, tn = (counts[key] for key in ("tp", "fp", "fn", "tn"))
        return {**counts, "support": tp + fp + fn + tn,
                "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / (tp + fn) if tp + fn else None,
                "false_positive_rate": fp / (fp + tn) if fp + tn else None}

    overall = {kind: metrics(observations, kind) for kind in ("dangerous", "missing_context")}
    excluded["unknown_risk"] = overall["dangerous"]["unknown"]
    excluded["unknown_context"] = overall["missing_context"]["unknown"]
    reviewers = sorted({event["reviewer_id"] for event, _ in observations})
    return {"format": "hyd-e3-human-evaluation/1", "n_questions": len(rows),
            "n_selected_reviewed": len(observations), "excluded": excluded, "overall": overall,
            "by_reviewer": {reviewer: {kind: metrics([(event, pred) for event, pred in observations
                                                     if event["reviewer_id"] == reviewer], kind)
                                       for kind in overall} for reviewer in reviewers},
            "selected_events": dict(selections), "status": "SHADOW_ONLY", "authority": False,
            "independence_verified": False,
            "limitation": "Human review is declared; explicit selection is not independent adjudication or identity verification."}
