# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.language import detect_language


def test_spanish_detection():
    assert detect_language("Hola, gracias por ayudarme con este proyecto.") == "es"


def test_english_detection():
    assert detect_language("Hello and thanks for the help.") == "en"
