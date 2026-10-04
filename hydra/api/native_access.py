# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Access control of the runtime-line routes.

API access follows exactly the gateway rules (``hydra.api.security.authenticate``): the configured
API key, loopback-only without one, and per-client keys (``hydra.<id>.<secret>``), which are
inference-only and therefore refused on these routes with 403. Admin access is deliberately stricter
than the platform's: deployment, outbox and replay operations need a configured ``HYDRA_ADMIN_TOKEN``
even from loopback."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import HTTPException, Request, status

from hydra.api.client_keys import client_route
from hydra.api.security import authenticate


@dataclass(frozen=True)
class SecurityConfig:
    api_token: str | None
    admin_token: str | None
    client_keys_file: str | None = None


def _provided_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("x-hydra-token") or request.headers.get("x-api-key")


def _matches(provided: str | None, expected: str | None) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def require_api_access(request: Request, config: SecurityConfig) -> str:
    """Caller identity (``api``, ``local:<host>``), or 401/403/503 as on every gateway route."""
    gateway = SimpleNamespace(api_key=config.api_token or "",
                              client_keys_file=config.client_keys_file or "data/keys/api-clients.json")
    identity = authenticate(gateway, request.client.host if request.client else "", _provided_token(request))
    if identity.startswith("client:"):
        client_route(identity, request.method, request.url.path)
    return identity


def require_admin_access(request: Request, config: SecurityConfig) -> str:
    # X-Hydra-Admin-Token is the gateway-wide admin header; the generic headers stay accepted.
    provided = request.headers.get("x-hydra-admin-token") or _provided_token(request)
    if not config.admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HYDRA admin token is not configured",
        )
    if not _matches(provided, config.admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HYDRA admin token",
        )
    # A domain-separated audit pseudonym, not a stored password verifier.
    return hmac.new(
        config.admin_token.encode(), b"hydra.admin.audit.v1", hashlib.sha256
    ).hexdigest()
