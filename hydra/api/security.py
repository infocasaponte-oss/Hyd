# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Gateway authentication shared by HTTP routes and the WebSocket endpoint.

* API routes: ``HYDRA_API_KEY`` (headers ``X-API-Key``, ``X-Hydra-Token`` or ``Authorization: Bearer``).
  Without a configured key only loopback clients are served.
* Admin routes (governance, IP, corpus approval, releases, model lifecycle, sync): additionally
  ``HYDRA_ADMIN_TOKEN`` in ``X-Hydra-Admin-Token``. Without a configured admin token only loopback
  clients are served, so a remote holder of the API key can never change governance state.
"""

from __future__ import annotations

import base64
import ipaddress
import secrets

from fastapi import HTTPException

_LOCAL_NAMES = {"localhost", "testclient"}


def is_loopback(host: str) -> bool:
    if host in _LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def _matches(provided: str | None, expected: str) -> bool:
    return bool(provided) and secrets.compare_digest(provided.encode(), expected.encode())


def authenticate(settings, host: str, token: str | None) -> str:
    """Return a stable caller identity (used for rate limiting) or raise 401/503."""
    from hydra.api.client_keys import lookup
    client = lookup(getattr(settings, 'client_keys_file', 'data/keys/api-clients.json'), token)
    if client:
        return 'client:' + client['id']
    if not settings.api_key:
        if token:
            raise HTTPException(401, 'invalid API key')
        if not is_loopback(host):
            raise HTTPException(503, "API key is not configured for remote access")
        return f"local:{host}"
    if not _matches(token, settings.api_key):
        raise HTTPException(401, "invalid API key")
    # One configured key -> one identity. The token itself is never hashed, logged or stored.
    return "api"


def authorize_admin(settings, host: str, token: str | None) -> str:
    if not settings.admin_token:
        if not is_loopback(host):
            raise HTTPException(503, "admin token is not configured for remote access")
        return f"admin-local:{host}"
    if not _matches(token, settings.admin_token):
        raise HTTPException(403, "admin token required")
    return "admin"


def websocket_token(headers, subprotocols: list[str]) -> str | None:
    """Token from ``X-API-Key``/``Authorization`` headers or a subprotocol (browsers cannot set
    WebSocket headers): ``hydra.token.b64.<base64url key>`` for any key, or ``hydra.token.<key>`` for
    keys that are already RFC 7230 tokens. Query strings are never accepted: they end up in logs."""
    token = headers.get("x-api-key") or headers.get("x-hydra-token")
    if not token and (authorization := headers.get("authorization", "")).lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token:
        return token
    for protocol in subprotocols:
        if protocol.startswith("hydra.token.b64."):
            encoded = protocol.removeprefix("hydra.token.b64.")
            try:
                return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return None
        if protocol.startswith("hydra.token."):
            return protocol.removeprefix("hydra.token.")
    return None
