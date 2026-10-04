# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""API clients can only point HYDRA at directories below HYDRA_REPOSITORIES_ROOT (CodeQL py/path-injection)."""
import os

import pytest
from fastapi.testclient import TestClient

from hydra.api.main import create_app
from hydra.core.paths import PathNotAllowed, confine, safe_id
from hydra.ledger.ip import export_bundle


def test_confine_keeps_paths_inside_the_root(tmp_path):
    root = tmp_path / "repos"
    (root / "calc").mkdir(parents=True)
    assert confine(root, "calc") == (root / "calc").resolve()
    escapes = ["..", "../secret", "calc/../../secret", str(tmp_path), "/etc"]
    if os.name == "nt":  # on POSIX "C:\\Windows" is just a file name inside the root
        escapes.append("C:\\Windows")
    for escape in escapes:
        with pytest.raises(PathNotAllowed):
            confine(root, escape)


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "..", "", ".hidden", "x" * 200])
def test_safe_id_rejects_path_like_values(bad):
    with pytest.raises(PathNotAllowed):
        safe_id(bad)


def test_goal_and_codegraph_routes_refuse_host_paths(settings, tmp_path):
    repos = tmp_path / "repos"
    repo = repos / "calc"
    repo.mkdir(parents=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("TOKEN = 'x'\n")
    app = create_app(settings.model_copy(update={"repositories_root": repos}))
    with TestClient(app) as client:
        for path in [str(outside), "../outside"]:
            assert client.post("/hydra/v1/goals", json={"goal": "fix it", "workspace": path}).status_code == 403
            assert client.post("/hydra/v1/world/codegraph", params={"path": path}).status_code == 403
        assert client.post("/hydra/v1/world/codegraph", params={"path": "calc"}).status_code == 200
        assert client.post("/hydra/v1/goals", json={"goal": "x", "workspace": "missing"}).status_code == 400


def test_invention_bundle_id_cannot_escape_the_bundle_directory(runtime, tmp_path):
    victim = tmp_path / "keep"
    victim.mkdir()
    with pytest.raises(PathNotAllowed):
        export_bundle(runtime.ip, "../keep", tmp_path / "bundles", runtime.signer)
    assert victim.exists()
