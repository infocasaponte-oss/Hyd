# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import os
import tempfile

# The HYDRA-SO runtime line keeps process-wide state under HYDRA_RUNTIME_DIR (./runtime by
# default). Tests get a private directory so they never touch, or race on, the developer's state.
# It must be set before any hydra.runtime module is imported.
os.environ.setdefault("HYDRA_RUNTIME_DIR", tempfile.mkdtemp(prefix="hydra-runtime-tests-"))
# Nor do they inherit the developer's tokens: hydra.runtime.config also reads ./.env, but the
# process environment wins, so empty values keep auth tests deterministic with or without .env.
for _token in ("HYDRA_ADMIN_TOKEN", "HYDRA_API_TOKEN", "HYDRA_API_KEY"):
    os.environ[_token] = ""
# Never write test keys into the developer's OS keyring: keep the legacy file layout in tests
# (tests/test_keystore.py exercises the keyring and keys-dir backends with an in-memory keyring).
os.environ["HYDRA_KEY_BACKEND"] = "legacy"
# The process-wide runtime line (hydra.runtime.api) must not adopt a developer's PostgreSQL from .env:
# its logs stay in the temporary HYDRA_RUNTIME_DIR (tests/test_runtime_backends.py covers PostgreSQL).
os.environ["HYDRA_RUNTIME_BACKEND"] = "file"

import pytest  # noqa: E402

from hydra.core.bootstrap import build_runtime  # noqa: E402
from hydra.core.config import Settings  # noqa: E402
from hydra.providers.mock import MockProvider  # noqa: E402
from hydra.registry.circuit_breaker import CircuitBreaker  # noqa: E402
from hydra.registry.models import Capabilities, ModelProfile  # noqa: E402
from hydra.registry.registry import ModelRegistry  # noqa: E402
from hydra.tools.sandbox import SubprocessSandbox  # noqa: E402


def model(id: str, tier: int = 2, local: bool = True, coding: float = 0.7, reasoning: float = 0.7,
          chat: float = 0.8, tools: float = 0.8, vision: float = 0.0, latency: float = 500,
          provider: str = "mock", **kw) -> ModelProfile:
    return ModelProfile(
        id=id, provider=provider, local=local, tier=tier, context_window=32768,
        capabilities=Capabilities(chat=chat, coding=coding, reasoning=reasoning, tools=tools,
                                  vision=vision, research=0.6),
        estimated_latency_ms=latency, **kw,
    )


def default_models() -> list[ModelProfile]:
    return [
        model("small", tier=1, coding=0.62, reasoning=0.62, chat=0.75, latency=200),
        model("medium", tier=3, coding=0.85, reasoning=0.85, chat=0.85, latency=800),
        model("large", tier=4, coding=0.93, reasoning=0.95, chat=0.9, latency=1500),
        model("cloud", tier=5, local=False, coding=0.95, reasoning=0.96, chat=0.95, latency=2000,
              input_cost=2.5, output_cost=10, provider="mock-cloud"),
    ]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(offline=True, sandbox_backend="subprocess", workspace_dir=tmp_path / "ws",
                    data_dir=tmp_path / "data", postgres_url="", redis_url="", nats_url="",
                    api_key="", admin_token="", client_keys_file=tmp_path / "clients.json")


@pytest.fixture
def mock() -> MockProvider:
    return MockProvider()


@pytest.fixture
async def runtime(settings, mock):
    rt = await build_runtime(
        settings,
        providers={"mock": mock, "mock-cloud": mock},
        registry=ModelRegistry(default_models(), CircuitBreaker(max_failures=2, cooldown_s=60)),
        sandbox=SubprocessSandbox(),
    )
    yield rt
    await rt.close()


@pytest.fixture(autouse=True)
def isolated_runtime_models(tmp_path_factory, monkeypatch):
    """The runtime line inventories ``HYDRA_MODELS_DIR`` (./models by default), hashing every GGUF.
    Tests must never read the developer's real models (tens of GB): point it at an empty directory."""
    import sys
    from dataclasses import replace

    api = sys.modules.get("hydra.runtime.api")
    if api is None:  # not imported by this test: nothing to isolate
        return
    from hydra.runtime.model_scout import HashCache

    models = tmp_path_factory.mktemp("models")
    monkeypatch.setattr(api, "settings", replace(api.settings, models_dir=str(models)))
    monkeypatch.setattr(api, "model_hash_cache", HashCache())


@pytest.fixture
def pg_url():
    """A fresh PostgreSQL database per test on the server in HYDRA_IT_POSTGRES (its user must be able to
    create databases). Append-only tables forbid TRUNCATE, so tests cannot share one database."""
    import os
    import uuid

    server = os.environ.get("HYDRA_IT_POSTGRES")
    if not server:
        pytest.skip("set HYDRA_IT_POSTGRES to run the PostgreSQL backends")
    psycopg = pytest.importorskip("psycopg")
    name = f"hydra_it_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    yield server.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
