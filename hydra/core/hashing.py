# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Canonical serialisation and hashing shared by the ledger, corpus, artifacts and releases."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 preserved."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def hash_obj(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def merkle_root(leaves: list[str]) -> str:
    """Merkle root over hex digests (duplicates the last node on odd levels)."""
    if not leaves:
        return sha256_hex(b"")
    level = [bytes.fromhex(x) for x in leaves]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_proof(leaves: list[str], index: int) -> list[tuple[str, str]]:
    """Inclusion proof: list of (sibling_hex, 'L'|'R')."""
    proof: list[tuple[str, str]] = []
    level = [bytes.fromhex(x) for x in leaves]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sib = index ^ 1
        proof.append((level[sib].hex(), "L" if sib < index else "R"))
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
        index //= 2
    return proof


def verify_merkle_proof(leaf: str, proof: list[tuple[str, str]], root: str) -> bool:
    node = bytes.fromhex(leaf)
    for sib, side in proof:
        s = bytes.fromhex(sib)
        node = hashlib.sha256(s + node if side == "L" else node + s).digest()
    return node.hex() == root
