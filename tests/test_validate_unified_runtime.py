# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.training.validate_unified_runtime import validate


def test_unified_validator_is_async_callable():
    assert callable(validate)
