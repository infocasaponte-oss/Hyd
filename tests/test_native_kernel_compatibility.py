# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.core import native_kernel, native_state
from hydra.runtime import api, kernel, state


def test_http_facade_and_legacy_import_share_canonical_kernel():
    assert kernel is native_kernel
    assert api.HydraKernel is native_kernel.HydraKernel


def test_legacy_state_shares_transition_validation():
    assert state is native_state
    assert state.validate_transition is native_state.validate_transition
