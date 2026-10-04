# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility aliases retain module globals and stored evidence behavior."""
import importlib

import pytest


@pytest.mark.parametrize('name', ['deployment_evidence_store', 'runtime_health_store',
                                  'runtime_health', 'runtime_evidence',
                                  'deployment_controller', 'traffic_router'])
def test_legacy_module_is_canonical_module(name):
    assert importlib.import_module('hydra.runtime.' + name) is importlib.import_module('hydra.deploy.' + name)


def test_early_environment_reader_retains_precedence(monkeypatch):
    from hydra.core.environment import _DOTENV, _env
    from hydra.runtime.config import _env as legacy_env
    monkeypatch.setitem(_DOTENV, 'HYDRA_PROBE_TEST', 'file-value')
    monkeypatch.delenv('HYDRA_PROBE_TEST', raising=False)
    assert legacy_env is _env
    assert _env('HYDRA_PROBE_TEST') == 'file-value'
    monkeypatch.setenv('HYDRA_PROBE_TEST', 'process-value')
    assert _env('HYDRA_PROBE_TEST') == 'process-value'
    assert _env('HYDRA_MISSING_PROBE_TEST', 'fallback') == 'fallback'


def test_legacy_paths_have_same_root_and_function():
    from hydra.core import runtime_paths
    from hydra.runtime import paths
    assert paths.RUNTIME_DIR == runtime_paths.RUNTIME_DIR
    assert paths.runtime_path is runtime_paths.runtime_path
