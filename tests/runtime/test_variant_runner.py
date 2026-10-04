# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime import variant_runner
from hydra.runtime.variant_runner import VariantRunError, VariantRunner


class Managed:
    def __init__(self):
        self.stopped = False

    async def stop(self):
        self.stopped = True


class Supervisor:
    def __init__(self):
        self.managed = Managed()

    async def start(self, argv):
        return self.managed


class EmptyMonitor:
    def __init__(self):
        self.peak_mb = 0
        self.samples = 0
        self.error = "nvidia-smi is not available"
        self._running = True

    async def run(self):
        return None

    def stop(self):
        self._running = False


@pytest.mark.asyncio
async def test_variant_runner_rejects_missing_gpu_telemetry(monkeypatch):
    supervisor = Supervisor()

    async def healthy(_url):
        return True

    monkeypatch.setattr(variant_runner, "PeakVramMonitor", EmptyMonitor)
    monkeypatch.setattr(variant_runner, "wait_for_health", healthy)

    async def workload():
        return {"ok": True}

    with pytest.raises(VariantRunError, match="nvidia-smi"):
        await VariantRunner(supervisor).run(
            argv=["server"],
            health_url="http://localhost/health",
            workload=workload,
        )

    assert supervisor.managed.stopped is True
