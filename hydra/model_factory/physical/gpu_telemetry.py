# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""GPU telemetry through nvidia-smi (peak VRAM monitor)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


class GpuTelemetryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class GpuSample:
    name: str
    memory_used_mb: int
    memory_total_mb: int
    utilization_gpu: int


async def sample_nvidia_smi(timeout_seconds: float = 5.0) -> list[GpuSample]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise GpuTelemetryUnavailable("nvidia-smi is not available") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise GpuTelemetryUnavailable("nvidia-smi timed out") from exc

    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise GpuTelemetryUnavailable(
            f"nvidia-smi failed with exit code {proc.returncode}: {detail}"
        )

    samples: list[GpuSample] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            samples.append(
                GpuSample(
                    name=parts[0],
                    memory_used_mb=int(parts[1]),
                    memory_total_mb=int(parts[2]),
                    utilization_gpu=int(parts[3]),
                )
            )
        except ValueError as exc:
            raise GpuTelemetryUnavailable(
                "nvidia-smi returned non-numeric telemetry"
            ) from exc

    if not samples:
        raise GpuTelemetryUnavailable("nvidia-smi returned no GPU samples")
    return samples


class PeakVramMonitor:
    def __init__(self, interval_seconds: float = 0.1):
        self.interval_seconds = interval_seconds
        self.peak_mb = 0
        self.samples = 0
        self.error: str | None = None
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                readings = await sample_nvidia_smi()
            except GpuTelemetryUnavailable as exc:
                self.error = str(exc)
                self._running = False
                return
            for reading in readings:
                self.peak_mb = max(self.peak_mb, reading.memory_used_mb)
                self.samples += 1
            await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        self._running = False
