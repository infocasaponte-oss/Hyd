# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""The non-offline bootstrap path (real providers) must start: every other test runs offline."""
from hydra.core.bootstrap import build_runtime
from hydra.core.config import Settings

UNREACHABLE = "http://127.0.0.1:9"  # nothing listens here: health probes fail fast


async def test_online_bootstrap_probes_providers_and_starts(tmp_path):
    settings = Settings(offline=False, runtime_monitor=False, sandbox_backend="subprocess",
                        workspace_dir=tmp_path / "ws", data_dir=tmp_path / "data",
                        postgres_url="", redis_url="", nats_url="", ollama_base_url=UNREACHABLE,
                        vllm_base_url=UNREACHABLE + "/v1", llamacpp_base_url=UNREACHABLE + "/v1",
                        cloud_api_key="")
    rt = await build_runtime(settings)
    try:
        # unreachable backends are excluded from routing until their health mark expires
        assert not rt.registry.provider_healthy("ollama")
        assert not rt.registry.provider_healthy("vllm")
        assert rt.registry.provider_healthy("mock")
    finally:
        await rt.close()
