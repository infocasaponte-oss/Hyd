# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.translation import GlossaryStore, split_text


def test_glossary_roundtrip(tmp_path):
    store = GlossaryStore(tmp_path)
    store.save("technical", {"World Model": "Modelo del Mundo"})
    assert store.load("technical")["World Model"] == "Modelo del Mundo"


def test_glossary_id_rejects_path_traversal(tmp_path):
    store = GlossaryStore(tmp_path)
    try:
        store.save("../escape", {"a": "b"})
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal should be rejected")


def test_chunker_preserves_text():
    text = "uno\n\ndos\n\ntres"
    chunks = split_text(text, max_chars=8)
    assert "\n\n".join(chunks) == text
