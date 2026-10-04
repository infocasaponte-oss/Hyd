# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Versioned benchmark suites (cases with expected content)."""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field


class BenchmarkCase(BaseModel):
    case_id: str
    capability: str
    prompt: str
    expected_contains: list[str] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0)


class BenchmarkSuite(BaseModel):
    suite_id: str
    version: str
    cases: list[BenchmarkCase]

    @property
    def suite_hash(self) -> str:
        body = self.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


RTX3060TI_ALPHA_SUITE = BenchmarkSuite(
    suite_id="hydra-3060ti-alpha",
    version="1",
    cases=[
        BenchmarkCase(
            case_id="exact-arithmetic",
            capability="reasoning.general",
            prompt="Return only the integer result of 37 * 19.",
            expected_contains=["703"],
        ),
        BenchmarkCase(
            case_id="translation-es-en",
            capability="language.translate",
            prompt="Translate to English, return only translation: El sistema está listo.",
            expected_contains=["system", "ready"],
        ),
        BenchmarkCase(
            case_id="structured-json",
            capability="chat.multilingual",
            prompt='Return only JSON with key "ok" and boolean value true.',
            expected_contains=['"ok"', "true"],
        ),
    ],
)
