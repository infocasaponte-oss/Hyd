# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Every backend implements exactly the same interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from hydra.core.contracts import ModelRequest, ModelResponse
from hydra.core.errors import ErrorKind, ModelError


class ModelProvider(ABC):
    @abstractmethod
    async def generate(self, model_id: str, request: ModelRequest) -> ModelResponse: ...

    @abstractmethod
    async def health(self) -> bool: ...

    async def close(self) -> None:
        return None


def http_error(exc: Exception, model_id: str) -> ModelError:
    """Translate transport errors into classified HYDRA errors."""
    if isinstance(exc, httpx.TimeoutException):
        return ModelError(f"{model_id}: timeout", ErrorKind.TIMEOUT)
    if isinstance(exc, httpx.ConnectError):
        return ModelError(f"{model_id}: runtime unreachable", ErrorKind.UNAVAILABLE)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        body = exc.response.text[:300].lower()
        if code == 429:
            return ModelError(f"{model_id}: rate limited", ErrorKind.RATE_LIMIT)
        if "out of memory" in body or "oom" in body:
            return ModelError(f"{model_id}: out of memory", ErrorKind.OOM)
        if code >= 500:
            return ModelError(f"{model_id}: HTTP {code}", ErrorKind.UNAVAILABLE)
        return ModelError(f"{model_id}: HTTP {code} {body}", ErrorKind.UNKNOWN)
    return ModelError(f"{model_id}: {exc}", ErrorKind.UNKNOWN)
