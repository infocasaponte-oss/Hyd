# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def scorer():
    path = Path(__file__).resolve().parents[1] / "scripts" / "score_grounded_eval.py"
    spec = importlib.util.spec_from_file_location("score_grounded_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


URL = "https://www.boe.es/buscar/act.php?id=BOE-A-2003-20254"


def test_rephrased_correct_answers_match_on_facts(scorer):
    fm = scorer.fact_match
    assert fm("boe_heading", f"Su encabezado es: Naturaleza del impuesto. {URL}",
              f"El artículo 1 se titula «Naturaleza del impuesto». Fuente: {URL}")
    assert fm("boe_repealed", "El metadato dice: «Derogada: No». No consta como derogada.",
              f"No. Según los metadatos, la norma no consta como derogada. Fuente: {URL}")
    assert fm("boe_rank_date", "Es una «Ley» publicada el 04/11/2003.",
              f"Su rango es «Ley» y se publicó en el BOE el 4 de noviembre de 2003. Fuente: {URL}")
    params = "La función `lr_warmup` recibe los parámetros: `optim`, `warmup_iter`, `base_lr`."
    assert fm("code_params", "Recibe `optim`, `warmup_iter` y `base_lr`.", params)  # subject optional
    assert fm("code_params", "La función `lr_warmup` recibe `optim`, `warmup_iter`, `base_lr`.", params)
    assert not fm("code_params", "Recibe `optim` y `base_lr`.", params)  # a parameter is missing
    methods = "La clase `TestSalesOrder` define 2 métodos: `test_totals`, `test_validations`."
    assert fm("code_methods", "Define 2 métodos: `test_totals`, `test_validations`.", methods)
    assert not fm("code_methods", "Define 3 métodos: `test_totals`, `test_validations`, `NAME`.", methods)


def test_wrong_facts_and_hallucinated_content_fail(scorer):
    fm = scorer.fact_match
    assert not fm("boe_sections", "El artículo 3 tiene 4 apartados numerados.",
                  f"El artículo 3 tiene 3 apartados numerados. Fuente: {URL}")
    assert not fm("boe_absent", "El artículo 17 establece las tarifas del servicio.",
                  "La fuente proporcionada solo incluye el artículo 1; no contiene el artículo 17, así que no puedo indicar qué establece.")
    assert fm("boe_absent", "La fuente no incluye el artículo 17, así que no puedo responder.",
              "La fuente proporcionada solo incluye el artículo 1; no contiene el artículo 17, así que no puedo indicar qué establece.")
    assert not fm("boe_quote", "Dice: «1. Texto cambiado.»", "dice literalmente: «1. Texto original.» Fuente: x")
    assert not fm("code_imports", "Importa `os`, `sys`, `json`.", "Importa 2 módulos: `os`, `sys`.")


def test_repeal_status_value_answers_are_understood(scorer):
    ref_no = "No. Según los metadatos, la norma no consta como derogada. Fuente: x"
    ref_si = "Sí. Según los metadatos, la norma consta como derogada. Fuente: x"
    assert scorer.fact_match("boe_repealed", "Su estado es «No». Fuente: x", ref_no)
    assert not scorer.fact_match("boe_repealed", "Su estado es «No». Fuente: x", ref_si)
    assert scorer.fact_match("boe_repealed", "Su estado de derogación es «Sí».", ref_si)
