# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import sys

import pytest

from hydra.runtime.build_supervisor import BuildSupervisor
from hydra.runtime.llama_factory import BuildCommand


@pytest.mark.asyncio
async def test_build_requires_real_output(tmp_path):
    command = BuildCommand(
        [sys.executable, "-c", "print('ok')"],
        tmp_path / "missing.gguf",
    )
    result = await BuildSupervisor().execute(command, timeout_seconds=10)
    assert result.ok is False
    assert result.artifact_sha256 is None


@pytest.mark.asyncio
async def test_build_hashes_created_output(tmp_path):
    output = tmp_path / "model.gguf"
    code = f"from pathlib import Path; Path(r'{output}').write_bytes(b'gguf')"
    result = await BuildSupervisor().execute(
        BuildCommand([sys.executable, "-c", code], output), timeout_seconds=10
    )
    assert result.ok is True
    assert len(result.artifact_sha256 or "") == 64
