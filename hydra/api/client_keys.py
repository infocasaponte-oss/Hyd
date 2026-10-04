# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Revocable application keys. Clients receive inference access only.

Credential format: ``hydra.<key_id>.<secret>``. The registry (``data/keys/api-clients.json``) keeps,
per client, the public ``key_id`` and a salted scrypt hash of the secret, never the secret itself.
The ``key_id`` selects one row, so a request costs at most one scrypt verification; a successful
verification is remembered in-process (per key id and registry entry), so later requests only pay a
constant-time comparison. Rows in the former unsalted SHA-256 format are rejected: re-issue those
clients with ``python -m scripts.manage_client_keys <id> --rotate``."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from pathlib import Path

from fastapi import HTTPException

INFERENCE_ROUTES = {
    ('POST', '/v1/chat/completions'), ('POST', '/v1/responses'),
    ('GET', '/v1/models'),
}
PREFIX = "hydra"
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
_CREDENTIAL = re.compile(r"^hydra\.([0-9a-f]{16})\.([A-Za-z0-9_-]{32,128})$")
_verified: dict[str, tuple[str, str]] = {}  # key_id -> (registry entry, secret) of the last success
_lock = threading.Lock()


def _scrypt(secret: str, salt: bytes, n: int, r: int, p: int) -> str:
    return hashlib.scrypt(secret.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32).hex()


def new_credential() -> tuple[str, dict]:
    """A fresh credential and the registry fields that verify it (the secret is not among them)."""
    key_id, secret, salt = secrets.token_hex(8), secrets.token_urlsafe(32), secrets.token_bytes(16)
    record = {"key_id": key_id, "scrypt": {**SCRYPT, "salt": salt.hex(), "hash": _scrypt(secret, salt, **SCRYPT)}}
    return f"{PREFIX}.{key_id}.{secret}", record


def _matches(row: dict, secret: str) -> bool:
    params = row["scrypt"]
    candidate = _scrypt(secret, bytes.fromhex(params["salt"]), int(params["n"]), int(params["r"]), int(params["p"]))
    return secrets.compare_digest(candidate, params["hash"])


def lookup(path, token):
    """The registry row for ``token``; None when it is not a registered client credential."""
    if not token or not Path(path).exists():
        return None
    parsed = _CREDENTIAL.match(token)
    if parsed is None:
        return None
    key_id, secret = parsed.groups()
    try:
        rows = json.loads(Path(path).read_text(encoding='utf-8'))['clients']
        row = next((r for r in rows if r.get('key_id') == key_id and 'scrypt' in r), None)
        if row is None:
            return None
        entry = json.dumps(row['scrypt'], sort_keys=True)
        with _lock:
            cached = _verified.get(key_id)
        ok = cached is not None and cached[0] == entry and secrets.compare_digest(cached[1], secret)
        if not ok and _matches(row, secret):
            ok = True
            with _lock:
                _verified[key_id] = (entry, secret)
        if not ok:
            return None
        if not row.get('enabled', False):
            raise HTTPException(401, 'client key revoked')
        return row
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, 'client key registry unavailable') from None


def client_route(identity, method, path):
    if identity.startswith('client:') and (method, path) not in INFERENCE_ROUTES:
        raise HTTPException(403, 'client key permits inference only')
