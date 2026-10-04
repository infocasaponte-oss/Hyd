"""Human annotation events bound to verbatim text, separate from routing labels."""

import hashlib
from datetime import datetime

FORMAT = "hyd-human-annotation/1"
RISK_KINDS = {"unknown", "benign", "dangerous", "security", "privacy", "high_risk"}
CONTEXT_STATES = {"unknown", "sufficient", "missing"}
ABSTAIN_REASONS = {"unknown", "none", "dangerous", "missing_context"}
FIELDS = {"format", "event_id", "record_sha256", "reviewer_id", "reviewer_kind", "created_at",
          "status", "risk_kind", "context_status", "abstain_reason"}


def validate_annotation(event, text):
    if not isinstance(event, dict) or set(event) != FIELDS:
        raise ValueError("annotation requires the exact versioned event fields")
    if event["format"] != FORMAT or event["reviewer_kind"] != "human":
        raise ValueError("annotation requires a declared human review")
    if not isinstance(text, str) or event["record_sha256"] != hashlib.sha256(text.encode()).hexdigest():
        raise ValueError("annotation text hash mismatch")
    for key in ("event_id", "reviewer_id"):
        if not isinstance(event[key], str) or not event[key].strip() or len(event[key]) > 200:
            raise ValueError(f"invalid annotation {key}")
    try:
        date = datetime.fromisoformat(event["created_at"])
    except (ValueError, TypeError):
        raise ValueError("invalid annotation timestamp") from None
    if date.utcoffset() is None:
        raise ValueError("annotation timestamp requires timezone")
    for key, allowed in (("risk_kind", RISK_KINDS), ("context_status", CONTEXT_STATES),
                         ("abstain_reason", ABSTAIN_REASONS), ("status", {"pending", "reviewed"})):
        if not isinstance(event[key], str) or event[key] not in allowed:
            raise ValueError(f"invalid annotation {key}")
    if event["status"] == "pending":
        if any(event[key] != "unknown" for key in ("risk_kind", "context_status", "abstain_reason")):
            raise ValueError("pending annotations cannot assert positive or negative targets")
    elif all(event[key] == "unknown" for key in ("risk_kind", "context_status", "abstain_reason")):
        raise ValueError("reviewed annotation requires an explicit target")
    if event["abstain_reason"] == "dangerous" and event["risk_kind"] != "dangerous":
        raise ValueError("dangerous abstention requires dangerous risk")
    if event["abstain_reason"] == "missing_context" and event["context_status"] != "missing":
        raise ValueError("missing-context abstention requires missing context")
    return dict(event)


def validate_annotations(events, text):
    if not isinstance(events, list):
        raise ValueError("annotations must be an event list")
    validated = [validate_annotation(event, text) for event in events]
    ids = [event["event_id"] for event in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate annotation event id")
    return validated
