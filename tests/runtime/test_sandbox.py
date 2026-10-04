# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.sandbox import DEFAULT_SANDBOX_IMAGE, OciSandbox


def test_sandbox_rejects_target_escape(tmp_path):
    sandbox = OciSandbox(tmp_path)
    with pytest.raises(ValueError):
        # Validation happens before the container process is started.
        import asyncio
        asyncio.run(sandbox.pytest("../outside"))


def test_sandbox_command_has_secure_defaults(tmp_path):
    sandbox = OciSandbox(tmp_path)
    assert sandbox.limits.memory == "1g"
    assert sandbox.limits.pids == 128
    assert sandbox.image == DEFAULT_SANDBOX_IMAGE
