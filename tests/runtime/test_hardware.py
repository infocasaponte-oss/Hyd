# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.hardware import resolve_profile


def test_rtx_3060_ti_profile():
    profile = resolve_profile("NVIDIA GeForce RTX 3060 Ti", 8192)
    assert profile.profile == "rtx3060ti"
    assert profile.quant == "Q4_K_M"
    assert profile.context == 8192
    assert profile.parallel == 1
