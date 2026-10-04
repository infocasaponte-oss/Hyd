# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio
from unittest.mock import AsyncMock

import pytest

from hydra.runtime.policy import ToolPermission
from hydra.runtime.sandbox import OciSandbox, SandboxResult
from hydra.runtime.tool_runtime import ToolRuntime
from hydra.runtime.tools import Workspace


@pytest.mark.asyncio
async def test_authorized_tests_use_readonly_sandbox(tmp_path):
    sandbox = OciSandbox(tmp_path)
    sandbox.pytest = AsyncMock(return_value=SandboxResult(True, "1 passed", 0))
    runtime = ToolRuntime(Workspace(tmp_path), sandbox=sandbox)
    result = await runtime.run("python.test", {"path": "."}, ToolPermission(allow_execute=True))
    assert result.ok and result.exit_code == 0
    sandbox.pytest.assert_awaited_once_with(".", read_only=True)


def test_workspace_mismatch_rejected(tmp_path):
    with pytest.raises(ValueError, match="workspace"):
        ToolRuntime(Workspace(tmp_path), sandbox=OciSandbox(tmp_path / "other"))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
async def test_timeout_or_cancellation_removes_only_its_container(tmp_path, monkeypatch, failure):
    calls = []

    class Process:
        returncode = 0

        async def communicate(self):
            raise failure()

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        calls.append(args)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    sandbox = OciSandbox(tmp_path)
    if failure is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await sandbox.pytest("-danger.py", read_only=True)
    else:
        assert (await sandbox.pytest("-danger.py", read_only=True)).exit_code == 124
    cmd = calls[0]
    name = cmd[cmd.index("--name") + 1]
    assert calls[1] == ("docker", "rm", "-f", name)
    assert cmd[-1] == "./-danger.py"
    assert "readonly" in cmd[cmd.index("--mount") + 1]
    assert cmd[cmd.index("--network") + 1] == "none"
