# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Answers about an article or code name absent from the supplied source must abstain."""
from types import SimpleNamespace

import pytest

from hydra.blackboard.state import BlackboardState
from hydra.core.contracts import HydraRequest, Message, RoutingDecision, TaskType
from hydra.verification.grounding import abstains, coverage, repair
from hydra.verification.verifier import Verifier

LAW = ("Responde usando solo la fuente.\nFUENTE:\nOrden TRM/844/2026.\n"
       "Artículo 1. Objeto.\n1. Esta orden regula las tarifas.\n2. Se aplica a SASEMAR.")
CODE = "FUENTE:\n```python\nimport os\n\ndef suma(a, b=1):\n    return a + b + len(os.sep)\n```"
ROUTE = RoutingDecision(task_type=TaskType.CHAT, complexity=0.2, risk=0.1)


def req(system: str | None, question: str) -> HydraRequest:
    messages = ([Message(role="system", content=system)] if system else []) + [Message(role="user", content=question)]
    return HydraRequest(messages=messages)


def test_absent_article_is_detected_and_present_one_is_not():
    assert coverage(req(LAW, "¿Qué establece el artículo 17 de la Orden TRM/844/2026?")).missing_articles == ("17",)
    assert not coverage(req(LAW, "¿Cómo se titula el artículo 1?")).missing


def test_without_source_material_general_knowledge_is_untouched():
    assert coverage(req(None, "¿Qué dice el artículo 17 de la Constitución?")) is None


def test_source_pasted_in_the_same_message_is_recognised():
    question = "Artículo 1. Objeto.\nEsta ley regula X.\n\n¿Qué dice el art. 4?"
    assert coverage(req(None, question)).missing_articles == ("4",)


def test_absent_code_name_is_detected_but_names_used_in_the_code_are_not():
    assert coverage(req(CODE, "¿Qué parámetros recibe la función `resta`?")).missing_names == ("resta",)
    assert not coverage(req(CODE, "¿Qué parámetros recibe `suma`?")).missing
    assert not coverage(req(CODE, "¿Para qué se usa `os` en el código?")).missing


def test_verifier_rejects_invented_content_and_verifies_grounded_abstention():
    request = req(LAW, "¿Qué establece el artículo 17 de la Orden TRM/844/2026?")
    invented = Verifier().verify(request, ROUTE, BlackboardState(),
                                 "El artículo 17 establece que las tarifas son una contraprestación por los servicios.")
    assert not invented.passed
    assert any(c.name == "source_coverage" and not c.passed for c in invented.checks)
    grounded = Verifier().verify(request, ROUTE, BlackboardState(),
                                 "La fuente proporcionada solo incluye el artículo 1; no contiene el artículo 17, "
                                 "así que no puedo indicar qué establece.")
    assert grounded.passed and grounded.verified
    assert next(c for c in grounded.checks if c.name == "answers_the_question").passed


def test_ordinary_answers_are_unaffected():
    result = Verifier().verify(req(LAW, "¿Cómo se titula el artículo 1?"), ROUTE, BlackboardState(),
                               "El artículo 1 se titula «Objeto».")
    assert all(c.name != "source_coverage" for c in result.checks)


def test_repair_is_a_recognised_abstention():
    for cov in (coverage(req(LAW, "Resume los artículos 17 y 20.")),
                coverage(req(CODE, "¿Qué devuelve la función `resta`?"))):
        text = repair(cov)
        assert abstains(text)
    assert "los artículos 17 y 20" in repair(coverage(req(LAW, "Resume los artículos 17 y 20.")))


@pytest.mark.asyncio
async def test_kernel_replaces_invented_answer_with_grounded_abstention():
    from hydra.core.kernel import HydraKernel

    kernel = object.__new__(HydraKernel)
    kernel.verifier = Verifier()
    events = []

    async def emit(*args, **kwargs):
        events.append(args)

    request = req(LAW, "¿Qué establece el artículo 17 de la Orden TRM/844/2026?")
    ctx = SimpleNamespace(request=request, route=ROUTE, state=BlackboardState(), degradations=[], emit=emit)
    invented = "El artículo 17 establece las tarifas del servicio de salvamento."
    verification = kernel.verifier.verify(request, ROUTE, ctx.state, invented)
    answer, checked, confidence = await kernel._enforce_source_coverage(ctx, invented, verification, 0.8)
    assert answer.startswith("La fuente proporcionada no incluye el artículo 17")
    assert checked.passed and checked.verified and confidence > 0
    assert ctx.degradations and events

    ok = "La fuente no incluye el artículo 17, así que no puedo indicar qué establece."
    same = await kernel._enforce_source_coverage(ctx, ok, kernel.verifier.verify(request, ROUTE, ctx.state, ok), 0.8)
    assert same[0] == ok


def test_plural_lists_and_citations_inside_a_pasted_source():
    assert coverage(req(LAW, "Compara los arts. 1, 4 y 9.")).missing_articles == ("4", "9")
    pasted = ("Artículo 1. Objeto.\nSin perjuicio de lo dispuesto en el artículo 142 de la Constitución.\n\n"
              "¿Qué regula el artículo 1?")
    assert not coverage(req(None, pasted)).missing  # 142 is cited by the source, not asked about


def test_official_numbers_dates_and_codes_are_not_arithmetic():
    from hydra.verification.math_check import expected_value

    for text in ("¿Qué establece el artículo 17 de la Orden TRM/844/2026?", "Ley 5/2007, de 20 de abril",
                 "Fuente: BOE-A-2003-20254", "publicada el 4/11/2003"):
        assert expected_value(text) is None, text
    for text, value in (("¿Cuánto es 12/4?", 3.0), ("¿2+2?", 4.0), ("calcula 100/2000", 0.05),
                        ("Resta 20-5 por favor", 15.0)):
        assert expected_value(text)[1] == value


def test_invented_source_links_are_removed_but_links_in_the_source_are_kept():
    from hydra.verification.grounding import strip_unsourced_urls
    source = "Artículo 5. Subsanación.\nDiez días. Más en https://www.boe.es/eli/es/l/2015/10/01/39\n\n¿Plazo?"
    answer = ("La subsanación se hace en diez días. Fuente: https://www.jurisprudencia.gob.es/ser/x?id=1 "
              "Ver https://www.boe.es/eli/es/l/2015/10/01/39.")
    cleaned, invented = strip_unsourced_urls(answer, source)
    assert invented == ["https://www.jurisprudencia.gob.es/ser/x?id=1"]
    assert cleaned == "La subsanación se hace en diez días. Ver https://www.boe.es/eli/es/l/2015/10/01/39."
    assert strip_unsourced_urls("Sin enlaces.", source) == ("Sin enlaces.", [])
    code = "Arreglado:\n```python\ndef add(a, b):\n    return a + b\n```\nFuente: https://example.org/inventada"
    cleaned, _ = strip_unsourced_urls(code, "def add(a, b):\n    return a - b\n")
    assert cleaned == "Arreglado:\n```python\ndef add(a, b):\n    return a + b\n```"
    cleaned, invented = strip_unsourced_urls("Plazo de diez días ([BOE](https://inventada.example/x)).", "Artículo 1. X.")
    assert cleaned == "Plazo de diez días (BOE)." and invented == ["https://inventada.example/x"]
