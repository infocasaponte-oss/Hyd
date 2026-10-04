# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.gpu_telemetry``."""
from __future__ import annotations

from hydra.model_factory.physical.gpu_telemetry import (  # noqa: F401
    GpuSample,
    GpuTelemetryUnavailable,
    PeakVramMonitor,
    sample_nvidia_smi,
)

__all__ = ['GpuSample', 'GpuTelemetryUnavailable', 'PeakVramMonitor', 'sample_nvidia_smi']

# Same module object under both paths: patching ``hydra.runtime.gpu_telemetry.<name>`` (tests, operators) must
# reach the code that runs, not a copy of its names.
import sys as _sys  # noqa: E402

_sys.modules[__name__] = _sys.modules["hydra.model_factory.physical.gpu_telemetry"]
