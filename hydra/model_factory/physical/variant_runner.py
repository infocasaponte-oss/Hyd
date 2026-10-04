# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Runs a variant server, waits for health and measures peak VRAM."""
from __future__ import annotations

import asyncio
from contextlib import suppress

from hydra.model_factory.physical.gpu_telemetry import PeakVramMonitor
from hydra.deploy.health_gate import wait_for_health
from hydra.model_factory.physical.process_supervisor import ProcessSupervisor


class VariantRunError(RuntimeError):
    pass


class VariantRunner:
    def __init__(self, supervisor: ProcessSupervisor | None = None):
        self.supervisor = supervisor or ProcessSupervisor()

    async def run(
        self,
        *,
        argv: list[str],
        health_url: str,
        workload,
    ):
        managed = await self.supervisor.start(argv)
        monitor = PeakVramMonitor()
        monitor_task = asyncio.create_task(monitor.run())
        try:
            if not await wait_for_health(health_url):
                raise VariantRunError("Model server did not become healthy")
            value = await workload()
            if monitor.error is not None or monitor.samples == 0:
                raise VariantRunError(
                    monitor.error or "GPU telemetry produced no samples"
                )
            return value, monitor.peak_mb, monitor.samples
        finally:
            monitor.stop()
            with suppress(asyncio.CancelledError):
                await monitor_task
            await managed.stop()
