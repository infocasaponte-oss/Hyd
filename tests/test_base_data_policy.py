# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.training.base_data_policy import admit_record, admit_source, admit_teacher, attribution_notice


@pytest.mark.parametrize("lic", ["CC-BY-SA-4.0", "CC-BY-SA-3.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1",
                                 "CC-BY-NC-4.0", "CC-BY-ND-4.0", "MPL-2.0", "", None, "Llama-4-Community",
                                 "some-custom-license"])
def test_licences_that_bind_or_are_unknown_are_rejected(lic):
    assert not admit_source(lic).allowed


@pytest.mark.parametrize("lic", ["public-domain", "CC0-1.0", "MIT", "Apache-2.0", "BSD-3-Clause",
                                 "CC-BY-4.0", "es-public-sector-reuse", "hydra-generated"])
def test_permissive_licences_are_admitted_with_their_obligation(lic):
    decision = admit_source(lic)
    assert decision.allowed
    if lic in ("MIT", "Apache-2.0", "CC-BY-4.0", "es-public-sector-reuse"):
        assert decision.obligation


def test_wikipedia_is_out_and_boe_and_stack_permissive_are_in():
    assert not admit_source("CC-BY-SA-4.0").allowed  # Wikipedia
    assert admit_source("es-public-sector-reuse").allowed  # BOE
    assert admit_record(["MIT"]).allowed and admit_record(["Apache-2.0", "MIT"]).allowed
    assert not admit_record(["MIT", "GPL-3.0"]).allowed  # every licence of the record must pass
    assert not admit_record([]).allowed


def test_only_permissive_teachers_can_be_distilled():
    assert admit_teacher("Apache-2.0").allowed and admit_teacher("MIT").allowed
    for lic in ("Llama-4-Community", "Gemma-Terms", "Qwen-License", "research-only", None):
        assert not admit_teacher(lic).allowed


def test_attribution_notice_groups_obligations_and_refuses_forbidden_sources():
    notice = attribution_notice([
        {"name": "BOE legislación consolidada", "license": "es-public-sector-reuse",
         "url": "https://www.boe.es/datosabiertos/", "attribution": "Fuente: Agencia Estatal BOE"},
        {"name": "org/repo /m.py", "license": "MIT"},
        {"name": "dominio público", "license": "public-domain"},
    ])
    assert "es-public-sector-reuse" in notice and "Fuente: Agencia Estatal BOE" in notice
    assert "MIT" in notice and "dominio público" not in notice
    with pytest.raises(ValueError):
        attribution_notice([{"name": "Wikipedia ES", "license": "CC-BY-SA-4.0"}])
