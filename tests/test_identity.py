# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.core.identity import creator_answer


def test_engine_creator_is_configured_not_generated():
    assert creator_answer("quen te creou", "Luis") == "O motor HYDRA foi creado por Luis."
    assert creator_answer("¿Quién te creó?", "Luis") == "El motor HYDRA fue creado por Luis."


def test_no_override_of_unrelated_or_weight_questions():
    assert creator_answer("Quen creou Qwen?", "Luis") is None
    assert creator_answer("quen te creou e resolve 2+2", "Luis") is None
    assert creator_answer("quen te creou", "") is None
