# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio
import sys

from hydra.model_factory.runner import CommandRunner


async def test_large_output_is_drained_with_bounded_tail():
    result = await CommandRunner().run([sys.executable, "-c",
        "import sys;sys.stdout.write('a'*1000000+'END');sys.stderr.write('b'*100000+'ERR')"])
    assert result.ok
    assert len(result.stdout) == 50000 and result.stdout.endswith("END")
    assert len(result.stderr) == 20000 and result.stderr.endswith("ERR")


async def test_timeout_stops_spawned_tree(tmp_path):
    marker = tmp_path / "orphan.txt"
    child = f"import time,pathlib;time.sleep(2);pathlib.Path({str(marker)!r}).write_text('orphan')"
    script = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(10)"
    result = await CommandRunner().run([sys.executable, "-c", script], timeout=.5)
    assert result.returncode == -9
    await asyncio.sleep(2)
    assert not marker.exists()


async def test_cancellation_stops_owned_process(tmp_path):
    marker = tmp_path / "cancelled.txt"
    script = f"import time,pathlib;time.sleep(2);pathlib.Path({str(marker)!r}).write_text('orphan')"
    task = asyncio.create_task(CommandRunner().run([sys.executable, "-c", script]))
    await asyncio.sleep(.3)
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    await asyncio.sleep(2)
    assert not marker.exists()
