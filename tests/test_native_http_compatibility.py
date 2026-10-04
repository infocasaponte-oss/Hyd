# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.api import native, runtime_routes
from hydra.runtime import api, workspaces
from hydra.tools import native_workspace


def test_standalone_entry_point_and_gateway_share_app_and_state():
    assert api is native
    assert runtime_routes.runtime_module() is native
    assert api.app is native.app
    assert api.kernel is native.kernel
    assert api.capture_uow is native.capture_uow


def test_workspace_compatibility_preserves_default_adapter():
    assert workspaces is native_workspace
    assert native.WorkspaceManager is native_workspace.WorkspaceManager
