# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.security_audit import SecurityAudit


def test_security_audit_never_requires_raw_token(tmp_path):
    events = JsonlEventStore(tmp_path / "events.jsonl")
    audit = SecurityAudit(events)
    audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/admin",
        outcome="allowed",
        identity_hash="a" * 64,
    )
    text = (tmp_path / "events.jsonl").read_text()
    assert "a" * 64 in text
    assert "Bearer" not in text
    assert events.verify_integrity().valid is True
