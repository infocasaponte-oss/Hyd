# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training import grounded_corpus_v1 as v1
from hydra.training import grounded_corpus_v2 as v2
from hydra.training.program import validate_corpus

TRAPS = '''import os
from collections import OrderedDict


def top(a):
    def inner(b):
        return b
    return inner(a)


class Box:
    def open(self):
        import json
        return json.dumps({})


if __name__ == "__main__":
    top(1)
'''


def record(identifier="r1", text=TRAPS):
    return {"id": identifier, "text": text, "repo_name": "org/repo", "path": "/m.py",
            "detected_licenses": ["MIT"], "revision_id": "x"}


def test_imports_follow_reading_order_and_from_x_counts_x():
    tree = v1.parse("import zlib\nfrom collections import OrderedDict\nimport abc\nfrom . import util\n")
    assert v2.imports_in_order(tree) == ["zlib", "collections", "abc", ".util"]


def test_functions_ignore_methods_nested_defs_and_main_guard():
    candidates, traps = v2.code_candidates(record(), "calcular_total_1")
    by_family = {c[0]: c for c in candidates}
    assert by_family["code_functions"][3] == "Define 1 función de nivel superior: `top`."
    assert by_family["code_imports"][3] == "Importa 3 módulos: `os`, `collections`, `json`."
    assert traps == {"functions": True, "imports": True}
    assert all(v2.verify(*c) for c in candidates)


def test_plural_typo_is_fixed():
    text = "def a():\n    pass\n\n\ndef b():\n    pass\n"
    answer = next(c for c in v2.code_candidates(record(text=text), "x")[0] if c[0] == "code_functions")[3]
    assert answer == "Define 2 funciones de nivel superior: `a`, `b`."
    assert "funciónes" not in json.dumps(v2.QUESTIONS, ensure_ascii=False)


def test_questions_state_the_rules_in_every_wording():
    assert all(q.endswith(v2.FUNCTION_RULE) for q in v2.QUESTIONS["code_functions"])
    assert all(q.endswith(v2.IMPORT_RULE) for q in v2.QUESTIONS["code_imports"])
    assert v2.QUESTIONS["boe_quote"] == v1.QUESTIONS["boe_quote"]


def test_import_verification_rejects_alphabetical_or_invented_lists():
    family, fields, source, answer = next(c for c in v2.code_candidates(record(), "x")[0] if c[0] == "code_imports")
    assert not v2.verify(family, fields, source, "Importa 3 módulos: `collections`, `json`, `os`.")
    assert not v2.verify(family, fields, source, "Importa 4 módulos: `os`, `collections`, `OrderedDict`, `json`.")


def test_build_prefers_hard_negatives_and_keeps_v1_splits(tmp_path):
    from tests.test_grounded_corpus_v1 import boe_record

    boe = tmp_path / "boe.jsonl"
    boe.write_text("".join(json.dumps(boe_record(f"BOE-A-2099-{i}"), ensure_ascii=False) + "\n" for i in range(40)),
                   encoding="utf-8")
    plain = "import os\n\n\ndef only(a):\n    return a\n"
    rows = [record(f"t{i}", f"# {i}\n" + TRAPS) for i in range(20)] + [record(f"p{i}", f"# {i}\n" + plain) for i in range(20)]
    code = tmp_path / "code.jsonl"
    code.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    quotas = dict.fromkeys(v2.QUESTIONS, 4)
    manifest = v2.build(tmp_path / "out", boe, code, quotas=quotas)
    validate_corpus(tmp_path / "out")
    assert manifest["hard_negatives"]["code_functions"] >= 2
    for split in v1.SPLITS:
        for line in (tmp_path / "out" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            assert v1.split_for(row["provenance"]["document_id"]) == split
