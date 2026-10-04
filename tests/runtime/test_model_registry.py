# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.runtime.model_registry import ModelRegistry, NoModelAvailable


def test_resolves_local_chat_model():
    model = ModelRegistry().resolve("chat.multilingual")
    assert model.model_id == "local-main"
    assert model.local is True


def test_unknown_capability_fails_closed():
    with pytest.raises(NoModelAvailable):
        ModelRegistry().resolve("vision.unknown")
