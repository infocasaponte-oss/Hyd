# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib

import pytest

from hydra.registry.native import ModelProfile, ModelRegistry, NoModelAvailable


@pytest.mark.parametrize("old,new", [
    ("hydra.runtime.model_registry", "hydra.registry.native"),
    ("hydra.runtime.executor", "hydra.scheduler.native_executor"),
    ("hydra.runtime.runtime_events", "hydra.deploy.events"),
    ("hydra.runtime.runtime_executor", "hydra.deploy.executor"),
    ("hydra.runtime.runtime_bridge", "hydra.deploy.bridge"),
    ("hydra.runtime.physical_inference", "hydra.providers.physical"),
])
def test_legacy_modules_share_canonical_globals(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def test_native_registry_never_selects_remote_or_disabled_for_local_execution():
    registry = ModelRegistry([
        ModelProfile("remote", frozenset({"chat"}), local=False, quality=1),
        ModelProfile("disabled", frozenset({"chat"}), enabled=False, quality=1),
        ModelProfile("local", frozenset({"chat"}), quality=0.1),
    ])
    assert registry.resolve("chat").model_id == "local"
    assert registry.resolve("chat", local_only=False).model_id == "remote"
    with pytest.raises(NoModelAvailable):
        registry.resolve("absent")
