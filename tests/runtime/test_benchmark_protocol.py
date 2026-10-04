# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.benchmark_protocol import StreamMetrics


def test_stream_metrics_require_real_token():
    metrics = StreamMetrics(started_at=1.0)
    try:
        _ = metrics.ttft_ms
    except ValueError as exc:
        assert "first token" in str(exc).lower()
    else:
        raise AssertionError("missing first token must not yield TTFT")
