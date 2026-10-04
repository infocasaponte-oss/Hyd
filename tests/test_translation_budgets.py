# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from fastapi.testclient import TestClient

from hydra.api.main import create_app
from hydra.edge.translation import chunk, protect, restore


def test_oversized_paragraph_is_split_at_whitespace():
    text = " ".join(["palabra"] * 2000)  # one paragraph of ~16k chars
    parts = chunk(text, max_chars=2500)
    assert len(parts) > 1 and all(len(p) <= 2500 for p in parts)
    assert "".join(parts) == text


def test_split_never_cuts_a_code_placeholder():
    source = ("texto " * 400) + "`codigo_importante()` " + ("más texto " * 400)
    protected, slots = protect(source)
    for max_chars in (2395, 2400, 2405, 2410):
        parts = chunk(protected, max_chars=max_chars)
        assert all(p.count("⟦") == p.count("⟧") for p in parts)
        assert restore("".join(parts), slots) == source


def test_translate_api_enforces_input_budget_and_accepts_runtime_schema(settings):
    settings = settings.model_copy(update={"max_input_chars": 20})
    with TestClient(create_app(settings)) as client:
        too_long = client.post("/v1/translate", json={"text": "hola " * 10, "target_language": "en"})
        assert too_long.status_code == 413
        assert client.put("/v1/glossaries/tech", json={"terms": {"hola": "hello"}}).status_code == 200
        ok = client.post("/v1/translate", json={"text": "hola", "target_language": "en", "glossary_id": "tech"})
        assert ok.status_code == 200 and ok.json()["target_language"] == "en"
        assert client.get("/v1/glossaries/tech").json() == {"hola": "hello"}
