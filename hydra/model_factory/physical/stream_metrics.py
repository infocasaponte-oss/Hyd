# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Streaming metrics: time to first token and tokens per second."""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter


@dataclass
class StreamMetrics:
    started_at: float
    first_token_at: float | None = None
    finished_at: float | None = None
    generated_tokens: int = 0

    @classmethod
    def start(cls) -> StreamMetrics:
        return cls(started_at=perf_counter())

    def token(self) -> None:
        now = perf_counter()
        if self.first_token_at is None:
            self.first_token_at = now
        self.generated_tokens += 1

    def finish(self) -> None:
        self.finished_at = perf_counter()

    @property
    def ttft_ms(self) -> float:
        if self.first_token_at is None:
            raise ValueError("No first token timestamp")
        return (self.first_token_at - self.started_at) * 1000

    @property
    def tokens_per_second(self) -> float:
        if self.first_token_at is None or self.finished_at is None:
            raise ValueError("Incomplete stream metrics")
        duration = self.finished_at - self.first_token_at
        if duration <= 0:
            raise ValueError("Invalid generation duration")
        return max(self.generated_tokens - 1, 0) / duration
