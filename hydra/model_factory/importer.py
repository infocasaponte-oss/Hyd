# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Importer: local directory, Hugging Face snapshot, safetensors, existing GGUF, LoRA,
internal checkpoint, or a model already installed in Ollama."""

from __future__ import annotations

import json
import os
from pathlib import Path

from hydra.model_factory.fingerprint import fingerprint
from hydra.model_factory.gguf import read_gguf
from hydra.model_factory.inspector import inspect
from hydra.model_factory.manifest import (
    Fingerprint,
    ModelArtifact,
    ModelFormat,
    ModelInspection,
    ModelLineage,
    ModelSource,
    SourceType,
)
from hydra.model_factory.runner import CommandRunner, ToolLocator, ToolMissing
from hydra.model_factory.store import FactoryStore

RUNTIMES = {
    ModelFormat.GGUF: ["llama.cpp", "ollama"],
    ModelFormat.SAFETENSORS: ["transformers", "vllm"],
    ModelFormat.AWQ: ["vllm"], ModelFormat.GPTQ: ["vllm"], ModelFormat.FP8: ["vllm"],
    ModelFormat.MLX: ["mlx"], ModelFormat.ONNX: ["onnxruntime"], ModelFormat.LORA: ["vllm", "ollama"],
}


def ollama_models_dir() -> Path:
    env = os.environ.get("OLLAMA_MODELS")
    return Path(env) if env else Path.home() / ".ollama" / "models"


def ollama_blob(name: str) -> tuple[Path, dict]:
    """Resolve an installed Ollama model to its GGUF blob and manifest."""
    model, _, tag = name.partition(":")
    tag = tag or "latest"
    root = ollama_models_dir()
    ns = "library" if "/" not in model else model.split("/")[0]
    repo = model if "/" not in model else model.split("/", 1)[1]
    manifest_path = root / "manifests" / "registry.ollama.ai" / ns / repo / tag
    if not manifest_path.exists():
        raise FileNotFoundError(f"Ollama model '{name}' is not installed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layer = next(lyr for lyr in manifest["layers"] if lyr["mediaType"].endswith("image.model"))
    return root / "blobs" / layer["digest"].replace(":", "-"), manifest


def variant_id_for(ins: ModelInspection) -> str:
    q = (ins.quantization or ins.dtype or "src").lower().replace("_", "-")
    return f"{ins.format.value}-{q}"


class ModelImporter:
    def __init__(self, store: FactoryStore, runner: CommandRunner | None = None,
                 tools: ToolLocator | None = None) -> None:
        self.store = store
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    async def _download_hf(self, source: ModelSource, dest: Path) -> Path:
        if self.tools.python_module("huggingface_hub"):
            import asyncio

            from huggingface_hub import snapshot_download  # type: ignore

            path = await asyncio.to_thread(snapshot_download, repo_id=source.location, revision=source.revision,
                                           local_dir=str(dest))
            return Path(path)
        cli = self.tools.binary("hf") or self.tools.binary("huggingface-cli")
        if cli is None:
            raise ToolMissing("install huggingface_hub (pip install huggingface_hub) to import from Hugging Face")
        cmd = [cli, "download", source.location, "--local-dir", str(dest)]
        if source.revision:
            cmd += ["--revision", source.revision]
        res = await self.runner.run(cmd)
        if not res.ok:
            raise RuntimeError(f"download failed: {res.stderr[-500:]}")
        return dest

    async def import_model(self, source: ModelSource, logical: str) -> ModelArtifact:
        extra: dict = {"source": source.model_dump()}
        fp: Fingerprint | None = None
        if source.source_type == SourceType.HUGGINGFACE:
            path = await self._download_hf(source, self.store.dir_for(logical) / "source")
            if source.trust_remote_code:
                extra["trust_remote_code"] = True
        elif source.source_type == SourceType.OLLAMA:
            path, manifest = ollama_blob(source.location)
            extra["ollama_name"] = source.location
            extra["ollama_manifest_layers"] = [lyr["mediaType"] for lyr in manifest["layers"]]
            g = read_gguf(path)
            # The blob name already is the SHA-256 of the weights: no need to re-hash gigabytes.
            fp = Fingerprint(weights_sha256=path.name.split("-", 1)[1], **_meta_hashes(g.metadata))
        else:
            path = Path(source.location).expanduser().resolve()
            if not path.exists():
                raise FileNotFoundError(path)

        ins = inspect(path)
        if fp is None:
            fp = fingerprint(path, read_gguf(path).metadata if ins.format == ModelFormat.GGUF and path.is_file()
                             else None)
        art = ModelArtifact(
            logical_model=logical, variant_id=variant_id_for(ins), architecture=ins.architecture,
            parameter_count=ins.parameters, format=ins.format, quantization=ins.quantization, path=str(path),
            context_length=ins.context_length, multimodal=ins.is_multimodal,
            runtime_targets=RUNTIMES.get(ins.format, []), size_bytes=ins.size_bytes, checksum=fp.weights_sha256,
            fingerprint=fp, metadata={**extra, "inspection": ins.model_dump(exclude={"metadata"})},
        )
        existing = next((a for a in self.store.artifacts.values()
                         if a.checksum == art.checksum and a.logical_model == logical), None)
        if existing is not None:
            return existing
        return self.store.add_artifact(art, ModelLineage(artifact_id=art.id, operation=f"import:{source.source_type.value}"))


def _meta_hashes(meta: dict) -> dict:
    import hashlib

    def h(obj) -> str:
        data = obj if isinstance(obj, bytes) else json.dumps(obj, sort_keys=True, default=str).encode()
        return hashlib.sha256(data).hexdigest()[:16]

    tok = {k: v for k, v in meta.items() if k.startswith("tokenizer.") and k != "tokenizer.chat_template"}
    cfg = {k: v for k, v in meta.items() if not k.startswith("tokenizer.")}
    out = {"tokenizer_hash": h(tok) if tok else None, "config_hash": h(cfg)}
    if t := meta.get("tokenizer.chat_template"):
        out["chat_template_hash"] = h(t.encode())
    return out
