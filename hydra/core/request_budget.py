# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Size limits of one request (input characters, output tokens, translation chunks).

Not the cognitive budget of a task (``hydra.core.budget``: time, tokens and calls spent while it runs,
whose ``BudgetExceeded`` the kernel turns into a degraded answer): exceeding these limits rejects the
request itself (HTTP 413/400). ``hydra.runtime.budgets`` re-exports them for the runtime line."""
from __future__ import annotations

from dataclasses import dataclass


class RequestBudgetExceeded(ValueError):
    pass


@dataclass(frozen=True)
class RequestBudget:
    max_input_chars: int = 50_000
    max_output_tokens: int = 4096
    max_chunks: int = 64

    def validate_input(self, text: str) -> None:
        if len(text) > self.max_input_chars:
            raise RequestBudgetExceeded(
                f"Input exceeds character budget: {len(text)} > {self.max_input_chars}"
            )

    def output_tokens(self, requested: int) -> int:
        if requested < 1:
            raise RequestBudgetExceeded("max_tokens must be positive")
        return min(requested, self.max_output_tokens)

    def validate_chunks(self, count: int) -> None:
        if count > self.max_chunks:
            raise RequestBudgetExceeded(f"Chunk budget exceeded: {count} > {self.max_chunks}")
