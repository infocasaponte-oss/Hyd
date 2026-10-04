# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import sys

import pytest

from hydra.runtime.process_supervisor import ProcessSupervisor


@pytest.mark.asyncio
async def test_supervisor_stops_process():
    managed = await ProcessSupervisor().start(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    await managed.stop(grace_seconds=0.1)
    assert managed.process.returncode is not None


@pytest.mark.asyncio
async def test_supervisor_drains_and_bounds_process_output():
    code = (
        "import sys; "
        "[print('line-' + str(i)) for i in range(1000)]; "
        "sys.stdout.flush()"
    )
    managed = await ProcessSupervisor().start([sys.executable, "-c", code])
    await managed.process.wait()
    if managed.drain_task is not None:
        await managed.drain_task

    output = managed.recent_output()
    assert "line-999" in output
    assert len(managed.output_tail) <= 200
