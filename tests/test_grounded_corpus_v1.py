# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.training import grounded_corpus_v1 as g
from hydra.training.program import validate_corpus

LAW = "\n".join([
    "Preámbulo de la norma.",
    "Artículo 1. Objeto.",
    "1. Esta ley regula el procedimiento administrativo común.",
    "2. Se aplica a todas las administraciones públicas.",
    "Artículo 2. Ámbito.",
    "Las disposiciones de esta ley rigen en todo el territorio.",
    "Disposición final única. Entrada en vigor.",
    "Esta ley entra en vigor al día siguiente.",
])
META = {"titulo": "Ley 9/2099, de 1 de enero, de pruebas.", "rango": "Ley", "numero_oficial": "9/2099",
        "departamento": "Jefatura del Estado", "fecha_publicacion": "20990102", "estatus_derogacion": "N"}
CODE = "import os\nfrom . import util\n\n\ndef suma(a, b=1, *xs, k, **kw):\n    return a + b\n\n\nclass Caja:\n    def abrir(self):\n        pass\n\n    def cerrar(self, fuerza):\n        pass\n"


def boe_record(document_id="BOE-A-2099-1"):
    return {"document_id": document_id, "metadata": dict(META), "text": LAW}


def code_record(identifier="abc"):
    return {"id": identifier, "text": f"# modulo {identifier}\n" + CODE, "repo_name": "org/repo", "path": "/m.py",
            "detected_licenses": ["MIT"], "revision_id": "r1"}


def test_articles_stop_at_dispositions_and_drop_repeated_numbers():
    arts = g.articles(LAW)
    assert arts["1"][0] == "Objeto" and len(arts["1"][1]) == 2
    assert arts["2"][1] == ["Las disposiciones de esta ley rigen en todo el territorio."]
    assert "1" not in g.articles(LAW + "\nArtículo 1. Repetido.\nTexto.")


def test_boe_candidates_cover_families_and_all_verify():
    candidates = g.boe_candidates(boe_record())
    families = {c[0] for c in candidates}
    assert families == {"boe_rank_date", "boe_repealed", "boe_heading", "boe_sections", "boe_quote", "boe_absent"}
    assert all(g.verify(*c) for c in candidates)
    rank = next(c for c in candidates if c[0] == "boe_rank_date")
    assert "«Ley»" in rank[3] and "2 de enero de 2099" in rank[3]
    assert g.norm_name(META) == "la Ley 9/2099"
    assert g.norm_name({"rango": "Real Decreto", "numero_oficial": "1/2000"}) == "el Real Decreto 1/2000"


def test_verify_rejects_unsupported_answers():
    family, fields, source, answer = next(c for c in g.boe_candidates(boe_record()) if c[0] == "boe_sections")
    assert not g.verify(family, fields, source, answer.replace("2 apartados", "3 apartados"))
    family, fields, source, answer = next(c for c in g.boe_candidates(boe_record()) if c[0] == "boe_quote")
    assert not g.verify(family, fields, source, answer.replace(".»", ",»"))
    family, fields, source, answer = next(c for c in g.boe_candidates(boe_record()) if c[0] == "boe_repealed")
    assert not g.verify(family, fields, source, "Sí." + answer[3:])


def test_code_candidates_use_ast_and_verify():
    candidates = g.code_candidates(code_record(), "calcular_total_1")
    by_family = {c[0]: c for c in candidates}
    assert set(by_family) == {"code_functions", "code_imports", "code_params", "code_methods", "code_absent"}
    assert "`suma`, `a`" not in by_family["code_functions"][3]
    assert by_family["code_imports"][3].endswith("`.util`, `os`.")
    assert "`a`, `b`, `*xs`, `k`, `**kw`" in by_family["code_params"][3]
    assert "`abrir`, `cerrar`" in by_family["code_methods"][3]
    assert all(g.verify(*c) for c in candidates)
    family, fields, source, answer = by_family["code_functions"]
    assert not g.verify(family, fields, source, answer.replace("`suma`", "`resta`"))


def test_unparseable_code_is_skipped():
    record = code_record()
    record["text"] = "def roto(:\n"
    assert g.code_candidates(record, "x") == []


def test_build_writes_valid_split_disjoint_corpus(tmp_path):
    boe = tmp_path / "boe.jsonl"
    code = tmp_path / "code.jsonl"
    boe.write_text("".join(json.dumps(boe_record(f"BOE-A-2099-{i}"), ensure_ascii=False) + "\n" for i in range(60)), encoding="utf-8")
    rows = [code_record(f"id{i}") for i in range(60)]
    rows.append(dict(code_record("gpl"), detected_licenses=["GPL-3.0"]))
    code.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = tmp_path / "corpus"
    manifest = g.build(out, boe, code, boe_per_family=5, code_per_family=5)
    assert manifest["inputs"]["code"]["permissive_records"] == 60
    assert sum(f["examples"] for f in manifest["files"].values()) == 55
    validate_corpus(out)
    docs = {}
    for split in g.SPLITS:
        for line in (out / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            assert row["training_allowed"] == (split == "train")
            assert int(row["wording_family"].rsplit("-", 1)[1]) in g.WORDING[split]
            docs.setdefault(row["provenance"]["document_id"], set()).add(split)
    assert all(len(splits) == 1 for splits in docs.values())
    with pytest.raises(FileExistsError):
        g.build(out, boe, code)


def test_contractions_and_length_fallback(tmp_path):
    assert g.contract("Resume el artículo 3 de el Real Decreto 1/2000.") == "Resume el artículo 3 del Real Decreto 1/2000."
    fits, policy = g.length_check(None, 768)
    assert policy["kind"] == "characters"
    assert fits([{"role": "user", "content": "x" * 100}])
    assert not fits([{"role": "user", "content": "x" * (g.MAX_EXAMPLE_CHARS + 1)}])
    record = boe_record()
    record["metadata"]["rango"], record["metadata"]["numero_oficial"] = "Real Decreto", "5/2099"
    answer = next(c for c in g.boe_candidates(record) if c[0] == "boe_absent")[3]
    assert "del Real Decreto 5/2099" in answer


def test_read_jsonl_ignores_partial_trailing_line(tmp_path):
    path = tmp_path / "growing.jsonl"
    path.write_bytes(b'{"a": 1}\n{"a": 2}\n{"a": ')
    rows, digest = g.read_jsonl(path)
    assert rows == [{"a": 1}, {"a": 2}]
    import hashlib
    assert digest == hashlib.sha256(b'{"a": 1}\n{"a": 2}\n').hexdigest()


def test_read_jsonl_keeps_complete_final_record_without_newline(tmp_path):
    import hashlib
    path = tmp_path / "no-newline.jsonl"
    path.write_bytes(b'{"a": 1}\n{"a": 2}')
    rows, digest = g.read_jsonl(path)
    assert rows == [{"a": 1}, {"a": 2}]
    assert digest == hashlib.sha256(b'{"a": 1}\n{"a": 2}').hexdigest()
    path.write_bytes(b'{"a": 1}')
    assert g.read_jsonl(path)[0] == [{"a": 1}]


def test_quote_includes_continuation_lines_of_the_apartado():
    record = boe_record()
    record["text"] = "\n".join([
        "Artículo 1. Objeto.",
        "1. Corresponde al órgano competente:",
        "a) Tramitar el procedimiento.",
        "b) Resolver el expediente.",
        "2. La resolución se notificará en el plazo de diez días.",
    ])
    sections = g.section_blocks(g.articles(record["text"])["1"][1])
    assert sections == [(1, "1. Corresponde al órgano competente:\na) Tramitar el procedimiento.\nb) Resolver el expediente."),
                        (2, "2. La resolución se notificará en el plazo de diez días.")]
    family, fields, source, answer = next(c for c in g.boe_candidates(record) if c[0] == "boe_quote")
    assert g.verify(family, fields, source, answer)
    full = dict(sections)[int(fields["sec"])]
    assert f"«{full}»" in answer
    truncated = answer.replace(full, full.split("\n")[0])
    if truncated != answer:
        assert not g.verify(family, fields, source, truncated)
    first = dict(fields, sec="1")
    assert not g.verify(family, first, source,
                        answer.replace(f"«{full}»", "«1. Corresponde al órgano competente:»"))


def test_relative_imports_keep_their_targets():
    tree = g.parse("from . import util, helpers\nfrom ..pkg import x\nimport os\n")
    assert g.imports(tree) == ["..pkg", ".helpers", ".util", "os"]


def test_wording_families_are_disjoint_across_splits():
    used = [set(v) for v in g.WORDING.values()]
    assert all(not (a & b) for i, a in enumerate(used) for b in used[i + 1:])
    assert all(len(q) > max(max(v) for v in g.WORDING.values()) for q in g.QUESTIONS.values())


def test_generator_digest_ignores_checkout_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.py", tmp_path / "crlf.py"
    lf.write_bytes(b"a = 1\nb = 2\n")
    crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
    assert g.source_sha256(lf) == g.source_sha256(crlf)


def test_non_positive_quotas_are_rejected(tmp_path):
    for kwargs in ({"boe_per_family": 0}, {"code_per_family": -1}, {"per_document": 0}):
        with pytest.raises(ValueError):
            g.build(tmp_path / "out", tmp_path / "b.jsonl", tmp_path / "c.jsonl", **kwargs)
