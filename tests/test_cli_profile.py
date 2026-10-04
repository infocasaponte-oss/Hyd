# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.cli import main
from hydra.edge.profiles import resolve_profile
from hydra.runtime.hardware import resolve_profile as runtime_resolve_profile


def test_small_gpu_is_still_used_and_cpu_only_needs_no_gpu():
    small = resolve_profile("NVIDIA GeForce RTX 3050", 4096)
    assert small.profile == "nvidia_low_vram" and small.gpu_layers == 99
    assert resolve_profile("cpu", 0).profile == "cpu_only"
    assert runtime_resolve_profile is resolve_profile  # one implementation


def test_hydra_so_profile_command_is_kept(capsys):
    assert main(["profile", "--gpu", "NVIDIA GeForce RTX 3060 Ti", "--vram-mb", "8192"]) in (0, None)
    out = json.loads(capsys.readouterr().out)
    assert (out["profile"], out["quant"], out["context"], out["parallel"]) == ("rtx3060ti", "Q4_K_M", 8192, 1)


def test_profile_requires_both_gpu_and_vram(capsys):
    assert main(["edge", "profile", "--gpu", "RTX 4090"]) == 2
