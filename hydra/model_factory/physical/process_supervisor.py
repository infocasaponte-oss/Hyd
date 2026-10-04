# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Long-running model server processes with bounded output."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ManagedProcess:
    process: asyncio.subprocess.Process
    output_tail: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    drain_task: asyncio.Task | None = None

    async def stop(self, grace_seconds: float = 5.0) -> None:
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=grace_seconds)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.drain_task is not None:
            await self.drain_task

    def recent_output(self) -> str:
        return "".join(self.output_tail)[-20_000:]


class ProcessSupervisor:
    async def _drain(
        self,
        stream: asyncio.StreamReader | None,
        output_tail: deque[str],
    ) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            output_tail.append(line.decode("utf-8", errors="replace"))

    async def start(self, argv: list[str]) -> ManagedProcess:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        managed = ManagedProcess(proc)
        managed.drain_task = asyncio.create_task(
            self._drain(proc.stdout, managed.output_tail)
        )
        return managed
