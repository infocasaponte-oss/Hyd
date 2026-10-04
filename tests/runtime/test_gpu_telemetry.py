# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio

import pytest

from hydra.runtime import gpu_telemetry
from hydra.runtime.gpu_telemetry import GpuTelemetryUnavailable, PeakVramMonitor


@pytest.mark.asyncio
async def test_sample_nvidia_smi_fails_when_binary_missing(monkeypatch):
    async def missing(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", missing)

    with pytest.raises(GpuTelemetryUnavailable, match="not available"):
        await gpu_telemetry.sample_nvidia_smi()


@pytest.mark.asyncio
async def test_peak_monitor_records_telemetry_error(monkeypatch):
    async def unavailable():
        raise GpuTelemetryUnavailable("no telemetry")

    monkeypatch.setattr(gpu_telemetry, "sample_nvidia_smi", unavailable)

    monitor = PeakVramMonitor(interval_seconds=0)
    await monitor.run()

    assert monitor.samples == 0
    assert monitor.peak_mb == 0
    assert monitor.error == "no telemetry"
