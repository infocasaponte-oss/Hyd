# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Anchor the HYDRA-SO runtime evidence chains in the signed platform ledger.

The runtime line keeps two hash chains (``runtime/events.jsonl`` and ``runtime/provenance.jsonl``)
that are verifiable but unsigned. Recording their heads in the Ed25519-signed, Merkle-anchored
ledger makes any later rewrite of runtime evidence detectable against a signed checkpoint.

* unchanged heads are not re-anchored;
* a chain that fails verification is never anchored: the failure itself is recorded once."""

from __future__ import annotations

from typing import Any

ANCHOR = "RUNTIME_CHAIN_ANCHOR"
BROKEN = "RUNTIME_CHAIN_INTEGRITY_FAILED"


def _last(ledger, event_type: str) -> dict[str, Any] | None:
    found = list(ledger.events(event_type))  # filtered by the backend (SQL on PostgreSQL)
    return found[-1].payload if found else None


def chain_heads(events, provenance) -> dict[str, Any]:
    ev, pv = events.verify_integrity(), provenance.verify_integrity()
    return {
        "events": {"valid": ev.valid, "records": ev.records, "head": events.head, "error": ev.error},
        "provenance": {"valid": pv.valid, "records": pv.records, "head": provenance.head, "error": pv.error},
    }


def anchor_runtime_chains(ledger, events, provenance) -> dict[str, Any] | None:
    """Append an anchor (or an integrity failure) when something changed. Returns what was appended."""
    heads = chain_heads(events, provenance)
    broken = {name: chain["error"] for name, chain in heads.items() if not chain["valid"]}
    if broken:
        if _last(ledger, BROKEN) == {"errors": broken}:
            return None
        ledger.append(BROKEN, {"errors": broken}, object_type="runtime_chain", object_id="hydra.runtime",
                      producer="runtime_anchor")
        return {"event_type": BROKEN, "errors": broken}
    payload = {name: {"records": chain["records"], "head": chain["head"]} for name, chain in heads.items()}
    if _last(ledger, ANCHOR) == payload:
        return None
    ledger.append(ANCHOR, payload, object_type="runtime_chain", object_id="hydra.runtime", producer="runtime_anchor")
    return {"event_type": ANCHOR, **payload}
