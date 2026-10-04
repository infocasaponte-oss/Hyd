# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""llama.cpp build commands (convert, quantize) and server arguments."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydra.model_factory.physical.quant_profiles import QuantProfile


@dataclass(frozen=True)
class BuildCommand:
    argv: list[str]
    output: Path


class LlamaCppFactory:
    """Builds argv only. A supervisor must execute and verify every output."""

    def __init__(self, llama_cpp_root: str | Path):
        self.root = Path(llama_cpp_root).resolve()

    def convert_command(self, source_model: str | Path, output_f16: str | Path) -> BuildCommand:
        script = self.root / "convert_hf_to_gguf.py"
        output = Path(output_f16).resolve()
        return BuildCommand(
            ["python", str(script), str(Path(source_model).resolve()), "--outfile", str(output),
             "--outtype", "f16"],
            output,
        )

    def quantize_command(
        self, input_f16: str | Path, output: str | Path, profile: QuantProfile
    ) -> BuildCommand:
        binary = self.root / "build" / "bin" / "llama-quantize"
        target = Path(output).resolve()
        return BuildCommand(
            [str(binary), str(Path(input_f16).resolve()), str(target), profile.quantization],
            target,
        )

    def server_args(self, model: str | Path, profile: QuantProfile) -> list[str]:
        binary = self.root / "build" / "bin" / "llama-server"
        return [
            str(binary),
            "-m", str(Path(model).resolve()),
            "-ngl", str(profile.gpu_layers),
            "-c", str(profile.context),
            "-np", str(profile.parallel),
            "--cache-type-k", profile.kv_k,
            "--cache-type-v", profile.kv_v,
        ]
