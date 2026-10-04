# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Automatic inspection before any conversion: architecture, dtype, parameters, MoE,
vision, context, chat template - and which runtimes/formats can support it.

Not every Hugging Face architecture converts to GGUF: llama.cpp must implement it.
"""

from __future__ import annotations

import json
from pathlib import Path

from hydra.model_factory import safetensors as st
from hydra.model_factory.gguf import read_gguf
from hydra.model_factory.manifest import ModelFormat, ModelInspection

# Architectures with a llama.cpp converter + graph (HF class names and GGUF arch names).
LLAMACPP_ARCHS = {
    "LlamaForCausalLM", "MistralForCausalLM", "MixtralForCausalLM", "Qwen2ForCausalLM", "Qwen2MoeForCausalLM",
    "Qwen3ForCausalLM", "Qwen3MoeForCausalLM", "Qwen2VLForConditionalGeneration",
    "Qwen2_5_VLForConditionalGeneration", "GemmaForCausalLM", "Gemma2ForCausalLM", "Gemma3ForCausalLM",
    "Gemma3ForConditionalGeneration", "Phi3ForCausalLM", "PhiForCausalLM", "Phi4MMForCausalLM",
    "DeepseekV2ForCausalLM", "DeepseekV3ForCausalLM", "StableLmForCausalLM", "StarCoder2ForCausalLM",
    "GPTNeoXForCausalLM", "FalconForCausalLM", "OlmoForCausalLM", "Olmo2ForCausalLM", "GraniteForCausalLM",
    "InternLM2ForCausalLM", "ChatGLMModel", "CohereForCausalLM", "Cohere2ForCausalLM", "ExaoneForCausalLM",
    "GptOssForCausalLM", "SmolLM3ForCausalLM", "Glm4ForCausalLM", "MiniCPMForCausalLM", "BertModel",
    "NomicBertModel", "LlavaForConditionalGeneration", "Mistral3ForConditionalGeneration",
    # GGUF arch names
    "llama", "mistral", "qwen2", "qwen2moe", "qwen3", "qwen3moe", "qwen2vl", "gemma", "gemma2", "gemma3",
    "phi2", "phi3", "deepseek2", "starcoder2", "gptneox", "falcon", "olmo", "olmo2", "granite", "internlm2",
    "chatglm", "command-r", "cohere2", "exaone", "gpt-oss", "smollm3", "glm4", "minicpm", "bert", "nomic-bert",
}
VLLM_ARCHS = {a for a in LLAMACPP_ARCHS if a[0].isupper()} | {
    "JambaForCausalLM", "MambaForCausalLM", "Phi3VForCausalLM", "LlavaNextForConditionalGeneration",
    "InternVLChatModel", "MiniCPMV", "PixtralForConditionalGeneration", "Llama4ForConditionalGeneration",
}
MLX_ARCHS = {
    "LlamaForCausalLM", "MistralForCausalLM", "MixtralForCausalLM", "Qwen2ForCausalLM", "Qwen2MoeForCausalLM",
    "Qwen3ForCausalLM", "Qwen3MoeForCausalLM", "GemmaForCausalLM", "Gemma2ForCausalLM", "Gemma3ForCausalLM",
    "Phi3ForCausalLM", "PhiForCausalLM", "DeepseekV2ForCausalLM", "DeepseekV3ForCausalLM", "StarCoder2ForCausalLM",
    "Olmo2ForCausalLM", "CohereForCausalLM", "GptOssForCausalLM",
}


class InspectionError(ValueError):
    pass


def detect_format(path: Path) -> ModelFormat:
    if path.is_file():
        with path.open("rb") as f:
            magic = f.read(4)
        if magic == b"GGUF":  # Ollama blobs have no extension
            return ModelFormat.GGUF
        if path.suffix == ".safetensors":
            return ModelFormat.SAFETENSORS
        if path.suffix == ".onnx":
            return ModelFormat.ONNX
        raise InspectionError(f"unknown model file: {path}")
    if (path / "adapter_config.json").exists():
        return ModelFormat.LORA
    if any(path.glob("*.onnx")):
        return ModelFormat.ONNX
    cfg = path / "config.json"
    if cfg.exists():
        qc = json.loads(cfg.read_text(encoding="utf-8")).get("quantization_config") or {}
        method = str(qc.get("quant_method", "")).lower()
        if method in ("awq", "gptq"):
            return ModelFormat(method)
        if method in ("fp8", "compressed-tensors") and "fp8" in json.dumps(qc).lower():
            return ModelFormat.FP8
        if (path / "weights.npz").exists() or any(path.glob("*.npz")) or "mlx" in json.dumps(qc).lower():
            return ModelFormat.MLX
    if any(path.glob("*.safetensors")):
        return ModelFormat.SAFETENSORS
    if any(path.glob("*.gguf")):
        return ModelFormat.GGUF
    raise InspectionError(f"cannot detect the model format of {path}")


def inspect_gguf(path: Path) -> ModelInspection:
    g = read_gguf(path)
    arch = g.architecture
    experts = g.arch_key("expert_count")
    meta_small = {k: v for k, v in g.metadata.items()
                  if not (isinstance(v, dict) and v.get("__array__")) and k != "tokenizer.chat_template"}
    return ModelInspection(
        format=ModelFormat.GGUF, architecture=arch, dtype=g.file_type or "unknown",
        parameters=g.parameters, context_length=g.arch_key("context_length"),
        vocab_size=(g.metadata.get("tokenizer.ggml.tokens") or {}).get("count")
        if isinstance(g.metadata.get("tokenizer.ggml.tokens"), dict) else g.arch_key("vocab_size"),
        embedding_length=g.arch_key("embedding_length"), layers=g.arch_key("block_count"),
        is_moe=bool(experts and experts > 1), experts=experts,
        is_multimodal=arch in ("clip", "mllama") or any(t.name.startswith(("v.", "mm.")) for t in g.tensors),
        quantization=g.file_type, has_chat_template="tokenizer.chat_template" in g.metadata,
        supports_gguf=True, supports_vllm=False, supports_mlx=False, size_bytes=g.size_bytes,
        files=[str(path)],
        metadata={**meta_small, "tensor_types": g.tensor_type_histogram()},
    )


def inspect_hf_dir(path: Path, fmt: ModelFormat) -> ModelInspection:
    cfg_path = path / "config.json"
    if not cfg_path.exists():
        raise InspectionError(f"{path} has no config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    text_cfg = cfg.get("text_config") or cfg
    arch = (cfg.get("architectures") or ["unknown"])[0]
    files = sorted(path.glob("*.safetensors"))
    summary = st.summarize(files) if files else {"parameters": 0, "dtype": cfg.get("dtype") or cfg.get("torch_dtype") or "unknown"}
    experts = (text_cfg.get("num_local_experts") or text_cfg.get("num_experts")
               or text_cfg.get("n_routed_experts"))
    tok_cfg = path / "tokenizer_config.json"
    template = bool(tok_cfg.exists() and json.loads(tok_cfg.read_text(encoding="utf-8")).get("chat_template")) \
        or (path / "chat_template.jinja").exists() or (path / "chat_template.json").exists()
    qc = cfg.get("quantization_config") or {}
    return ModelInspection(
        format=fmt, architecture=arch,
        dtype=str(cfg.get("dtype") or cfg.get("torch_dtype") or summary["dtype"]).upper().replace("BFLOAT16", "BF16").replace(
            "FLOAT16", "F16").replace("FLOAT32", "F32"),
        parameters=summary["parameters"],
        context_length=text_cfg.get("max_position_embeddings"),
        vocab_size=text_cfg.get("vocab_size"), embedding_length=text_cfg.get("hidden_size"),
        layers=text_cfg.get("num_hidden_layers"),
        is_moe=bool(experts and experts > 1), experts=experts,
        is_multimodal=bool(cfg.get("vision_config") or cfg.get("audio_config")) or "VL" in arch
        or "ConditionalGeneration" in arch,
        quantization=qc.get("quant_method") and f"{qc.get('quant_method')}-{qc.get('bits', '')}".rstrip("-"),
        has_chat_template=template,
        supports_gguf=arch in LLAMACPP_ARCHS and fmt == ModelFormat.SAFETENSORS,
        supports_vllm=arch in VLLM_ARCHS,
        supports_mlx=arch in MLX_ARCHS and fmt in (ModelFormat.SAFETENSORS, ModelFormat.MLX),
        size_bytes=sum(f.stat().st_size for f in path.iterdir() if f.is_file()),
        files=[str(f) for f in files],
        metadata={"config": {k: v for k, v in cfg.items() if not isinstance(v, (dict, list))},
                  "dtypes": summary.get("dtypes", {})},
    )


def inspect(path: str | Path) -> ModelInspection:
    p = Path(path)
    if not p.exists():
        raise InspectionError(f"{p} does not exist")
    fmt = detect_format(p)
    if fmt == ModelFormat.GGUF:
        return inspect_gguf(p if p.is_file() else next(p.glob("*.gguf")))
    if fmt == ModelFormat.LORA:
        cfg = json.loads((p / "adapter_config.json").read_text(encoding="utf-8"))
        files = sorted(p.glob("*.safetensors"))
        summary = st.summarize(files) if files else {"parameters": 0, "dtype": "unknown"}
        return ModelInspection(format=fmt, architecture=f"lora:{cfg.get('base_model_name_or_path', '?')}",
                               dtype=summary["dtype"], parameters=summary["parameters"],
                               size_bytes=sum(f.stat().st_size for f in p.iterdir() if f.is_file()),
                               files=[str(f) for f in files],
                               metadata={"r": cfg.get("r"), "alpha": cfg.get("lora_alpha"),
                                         "target_modules": cfg.get("target_modules"),
                                         "base_model": cfg.get("base_model_name_or_path")})
    if p.is_file():
        summary = st.summarize([p])
        return ModelInspection(format=fmt, architecture="unknown", dtype=summary["dtype"],
                               parameters=summary["parameters"], size_bytes=p.stat().st_size, files=[str(p)])
    return inspect_hf_dir(p, fmt)
