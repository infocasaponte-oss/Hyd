# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Registry sync: an approved variant becomes a routable ModelProfile whose capabilities
are the *measured* eval scores - HYDRA starts using it wherever it proves better."""

from __future__ import annotations

from hydra.evals.engine import EvalReport
from hydra.model_factory.manifest import ModelArtifact, ModelVariant
from hydra.registry.models import Capabilities, ModelProfile, ModelQuirks


def tier_for(parameters: int | None) -> int:
    p = (parameters or 0) / 1e9
    return 1 if p < 2.5 else 2 if p < 9.5 else 3 if p < 20 else 4 if p < 60 else 5


def provider_for(variant: ModelVariant) -> str:
    return {"ollama": "ollama", "vllm": "vllm", "llamacpp": "llamacpp", "mlx": "vllm"}.get(variant.runtime, "vllm")


def profile_for(variant: ModelVariant, artifact: ModelArtifact, report: EvalReport | None = None,
                enabled: bool = False) -> ModelProfile:
    s = {k: v.score for k, v in (report.suites.items() if report else [])}
    reasoning = s.get("reasoning", variant.reasoning_score or 0.6)
    coding = s.get("coding", variant.coding_score or 0.6)
    caps = Capabilities(
        chat=round((reasoning + s.get("hallucination", 0.6)) / 2 + 0.2, 3) if report else 0.7,
        reasoning=reasoning, coding=coding, tools=s.get("tool_use", 0.5), vision=s.get("vision", 0.0),
        research=round((reasoning + s.get("hallucination", 0.5)) / 2, 3), routing=s.get("structured", 0.5),
    )
    return ModelProfile(
        id=variant.id,
        provider=provider_for(variant),
        runtime_model=variant.runtime_model,
        endpoint=variant.endpoint,
        local=True,
        tier=tier_for(artifact.parameter_count),
        context_window=min(artifact.context_length or 8192, 131072),
        capabilities=caps,
        estimated_latency_ms=report.latency_p50_ms if report and report.latency_p50_ms else 1000,
        enabled=enabled,
        quirks=ModelQuirks(native_json_schema=s.get("structured", 1.0) >= 0.5, native_images=artifact.multimodal),
        logical_model=variant.logical_model,
        variant_id=variant.id,
    )
