# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.edge import autobuild as ab
from hydra.edge.profiles import resolve_profile

GPU = resolve_profile("NVIDIA GeForce RTX 3060 Ti", 8192)
CPU = GPU.model_copy(update={"vram_mb": 0})


def test_gpu_result_without_vram_evidence_is_not_eligible():
    assert ab.eligible({"stable": True, "vram_peak_mb": 5000}, GPU)
    assert not ab.eligible({"stable": True, "vram_peak_mb": None}, GPU)
    assert not ab.eligible({"stable": True, "vram_peak_mb": 5000, "telemetry_error": "nvidia-smi timed out"}, GPU)


def test_cpu_profile_needs_no_gpu_telemetry():
    assert ab.eligible({"stable": True, "vram_peak_mb": None}, CPU)


async def test_autobuild_never_selects_a_candidate_without_telemetry(monkeypatch):
    fast_but_blind = {"stable": True, "tokens_per_second": 500.0, "ttft_ms": 10.0, "vram_peak_mb": None,
                      "telemetry_error": "no GPU telemetry samples", "fully_on_gpu": True}
    measured = {"stable": True, "tokens_per_second": 60.0, "ttft_ms": 200.0, "vram_peak_mb": 5200,
                "fully_on_gpu": True}
    results = iter([fast_but_blind, measured])

    async def fake_bench(server, model_path, candidate, profile, port):
        return {**next(results), "candidate": candidate.model_dump()}

    monkeypatch.setattr(ab, "bench_llama_server", fake_bench)
    candidates = [ab.BuildCandidate(quant="Q4_K_M", context=8192), ab.BuildCandidate(quant="Q4_K_M", context=4096)]
    manifest = await ab.autobuild(model="m.gguf", runtime="llama.cpp", llama_server="llama-server",
                                  profile=GPU, candidates=candidates)
    assert manifest.selected is not None
    assert manifest.selected["candidate"]["context"] == 4096
    assert len(manifest.all_results) == 2


async def test_autobuild_selects_nothing_when_no_gpu_run_has_telemetry(monkeypatch):
    async def blind(server, model_path, candidate, profile, port):
        return {"stable": True, "tokens_per_second": 90.0, "ttft_ms": 50.0, "vram_peak_mb": None,
                "telemetry_error": "nvidia-smi is not available", "candidate": candidate.model_dump()}

    monkeypatch.setattr(ab, "bench_llama_server", blind)
    manifest = await ab.autobuild(model="m.gguf", runtime="llama.cpp", llama_server="llama-server",
                                  profile=GPU, candidates=[ab.BuildCandidate(quant="Q4_K_M", context=8192)])
    assert manifest.selected is None
