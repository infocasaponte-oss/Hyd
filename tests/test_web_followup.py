# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.tools.web_context import web_query, requested_web, search_terms
from hydra.memory.context import ContextBudget, ContextCompiler


def test_followup_uses_previous_search():
    messages = [{"role": "user", "content": "busca teoremas en internet"},
                {"role": "assistant", "content": "Abre un navegador"},
                {"role": "user", "content": "que los busques tu?"}]
    assert web_query(messages) == "busca teoremas en internet"
    assert requested_web(web_query(messages))


def test_unrelated_turn_does_not_search_again():
    assert web_query([{"role": "user", "content": "busca teoremas en internet"},
                      {"role": "user", "content": "por que?"}]) == "por que?"


def test_new_search_overrides_old_query():
    assert web_query([{"role": "user", "content": "busca teoremas en internet"},
                      {"role": "user", "content": "busca asyncio en internet"}]) == "busca asyncio en internet"


def test_open_theorem_search_uses_mathematical_terminology():
    assert search_terms("busca en internet teoremas sen resolver?") == "problemas matemáticos abiertos conjeturas sin resolver?"
    assert search_terms("teorema de Pitágoras") == "teorema de Pitágoras"


def test_oversized_web_evidence_is_not_silently_dropped():
    result = ContextCompiler().compile(ContextBudget.for_window(2048), "system",
        [{"role": "user", "content": "Search"}], documents=["retrieved source: " + "evidence " * 1000])
    assert "retrieved source:" in result[0]["content"]
    assert "[truncated]" in result[0]["content"]
