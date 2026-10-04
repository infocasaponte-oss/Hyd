# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.llama_factory import LlamaCppFactory
from hydra.runtime.quant_profiles import RTX3060TI_PROFILES


def test_quantize_command_uses_selected_quant(tmp_path):
    factory = LlamaCppFactory(tmp_path / "llama.cpp")
    profile = RTX3060TI_PROFILES[1]
    command = factory.quantize_command(
        tmp_path / "f16.gguf", tmp_path / "q4.gguf", profile
    )
    assert command.argv[-1] == "Q4_K_M"
    assert "llama-quantize" in command.argv[0]


def test_server_args_use_3060ti_profile(tmp_path):
    factory = LlamaCppFactory(tmp_path / "llama.cpp")
    args = factory.server_args(tmp_path / "model.gguf", RTX3060TI_PROFILES[1])
    assert "-ngl" in args
    assert "8192" in args
    assert "q8_0" in args
