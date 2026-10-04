# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Adapter Factory: one base model + many LoRA adapters instead of many full models.

    qwen-7b base ── router adapter ── critic adapter ── tool adapter
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class AdapterSpec(BaseModel):
    logical_model: str  # e.g. hydra-critic
    base_model: str  # e.g. qwen-7b (HF id / path / ollama name)
    adapter_name: str  # e.g. critic-v7
    adapter_path: str
    runtime: str = "vllm"  # vllm (--lora-modules) | ollama (ADAPTER)
    endpoint: str | None = None


class AdapterRegistry:
    """LoRA adapters by logical model, in the ``models/adapters.json`` document (``hydra.core.docstore``)."""

    def __init__(self, path: Path, docs=None) -> None:
        from hydra.core.docstore import DocumentStore, KeyedModels

        self.path = path
        self._registry = KeyedModels((docs or DocumentStore()).document("models/adapters.json", path), AdapterSpec)

    @property
    def adapters(self) -> dict[str, AdapterSpec]:
        return self._registry.all()

    def register(self, spec: AdapterSpec) -> AdapterSpec:
        return self._registry.put(spec.logical_model, spec)

    def for_base(self, base: str) -> list[AdapterSpec]:
        return [a for a in self.adapters.values() if a.base_model == base]

    @staticmethod
    def vllm_flags(specs: list[AdapterSpec]) -> list[str]:
        """vLLM serves every adapter of a base from a single process."""
        if not specs:
            return []
        return ["--enable-lora", "--lora-modules", *[f"{s.adapter_name}={s.adapter_path}" for s in specs],
                "--max-loras", str(max(1, len(specs)))]
