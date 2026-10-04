# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Intelligent retry: errors become cognitive decisions, not blind loops."""

from __future__ import annotations

import asyncio
import json
from enum import Enum


class ErrorKind(str, Enum):
    TIMEOUT = "timeout"
    OOM = "oom"
    INVALID_JSON = "invalid_json"
    TOOL_UNAVAILABLE = "tool_unavailable"
    RATE_LIMIT = "rate_limit"
    MODEL_REFUSAL = "model_refusal"
    HALLUCINATED_TOOL = "hallucinated_tool"
    PERMISSION = "permission"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RetryAction(str, Enum):
    HEDGE = "hedge_request"
    SMALLER_MODEL = "smaller_model"
    RETRY_STRUCTURED = "retry_structured_output"
    REPLAN_WITHOUT_TOOL = "replan_without_tool"
    ALTERNATE_PROVIDER = "alternate_provider"
    REPHRASE = "rephrase"
    FAIL = "fail"


class HydraError(Exception):
    kind: ErrorKind = ErrorKind.UNKNOWN

    def __init__(self, message: str = "", kind: ErrorKind | None = None, **info) -> None:
        super().__init__(message)
        if kind is not None:
            self.kind = kind
        self.info = info


class ModelError(HydraError):
    pass


class ToolError(HydraError):
    pass


def classify(error: BaseException) -> ErrorKind:
    if isinstance(error, HydraError):
        return error.kind
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return ErrorKind.TIMEOUT
    if isinstance(error, json.JSONDecodeError):
        return ErrorKind.INVALID_JSON
    if isinstance(error, PermissionError):
        return ErrorKind.PERMISSION
    if isinstance(error, MemoryError):
        return ErrorKind.OOM
    text = str(error).lower()
    if "out of memory" in text or "oom" in text:
        return ErrorKind.OOM
    if "429" in text or "rate limit" in text:
        return ErrorKind.RATE_LIMIT
    if "timeout" in text or "timed out" in text:
        return ErrorKind.TIMEOUT
    if "connect" in text or "503" in text or "502" in text:
        return ErrorKind.UNAVAILABLE
    return ErrorKind.UNKNOWN


STRATEGY: dict[ErrorKind, RetryAction] = {
    ErrorKind.TIMEOUT: RetryAction.HEDGE,
    ErrorKind.OOM: RetryAction.SMALLER_MODEL,
    ErrorKind.INVALID_JSON: RetryAction.RETRY_STRUCTURED,
    ErrorKind.TOOL_UNAVAILABLE: RetryAction.REPLAN_WITHOUT_TOOL,
    ErrorKind.HALLUCINATED_TOOL: RetryAction.REPLAN_WITHOUT_TOOL,
    ErrorKind.RATE_LIMIT: RetryAction.ALTERNATE_PROVIDER,
    ErrorKind.UNAVAILABLE: RetryAction.ALTERNATE_PROVIDER,
    ErrorKind.MODEL_REFUSAL: RetryAction.REPHRASE,
    ErrorKind.PERMISSION: RetryAction.FAIL,
    ErrorKind.UNKNOWN: RetryAction.ALTERNATE_PROVIDER,
}


def decide(error: BaseException) -> tuple[ErrorKind, RetryAction]:
    kind = classify(error)
    return kind, STRATEGY[kind]
