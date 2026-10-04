# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Publisher: make a built artifact servable (Ollama model, or a vLLM / MLX / llama-server endpoint)."""

from __future__ import annotations

import re

from hydra.model_factory.manifest import ModelArtifact, ModelFormat, ModelVariant
from hydra.model_factory.quantizer import OllamaQuantizer

RUNTIME_OF = {ModelFormat.GGUF: "ollama", ModelFormat.OLLAMA: "ollama", ModelFormat.AWQ: "vllm",
              ModelFormat.GPTQ: "vllm", ModelFormat.FP8: "vllm", ModelFormat.SAFETENSORS: "vllm",
              ModelFormat.MLX: "mlx", ModelFormat.ONNX: "onnx"}


def ollama_name(logical: str, variant: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", f"hydra-{logical}-{variant}".lower()).strip("-")[:120] + ":latest"


class PublishError(RuntimeError):
    pass


class Publisher:
    def __init__(self, ollama: OllamaQuantizer | None = None) -> None:
        self.ollama = ollama or OllamaQuantizer()

    async def publish(self, artifact: ModelArtifact, endpoint: str | None = None,
                      runtime_model: str | None = None) -> ModelVariant:
        runtime = RUNTIME_OF.get(artifact.format, "vllm")
        name = runtime_model
        if runtime == "ollama":
            if artifact.format == ModelFormat.OLLAMA or artifact.metadata.get("ollama_name"):
                name = artifact.metadata.get("ollama_name") or artifact.path.removeprefix("ollama://")
            else:
                name = name or ollama_name(artifact.logical_model, artifact.variant_id)
                res = await self.ollama.create(name, artifact.path)
                if not res.ok:
                    raise PublishError(f"ollama create failed: {res.stderr[-500:]}")
        elif endpoint is None:
            raise PublishError(f"{artifact.format.value} artifacts are served by {runtime}: pass its endpoint")
        return ModelVariant(
            id=f"{artifact.logical_model}:{artifact.variant_id}", logical_model=artifact.logical_model,
            artifact_id=artifact.id, format=artifact.format, quantization=artifact.quantization,
            runtime=runtime, runtime_model=name or artifact.path, endpoint=endpoint,
            hardware_targets=artifact.runtime_targets,
        )
