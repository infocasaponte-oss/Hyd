# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training import grounded_corpus_v1 as v1
from hydra.training import grounded_corpus_v5 as v5
from hydra.training.program import validate_corpus


def test_import_rule_is_consistent_with_the_relative_label():
    assert all(q.endswith(v5.IMPORT_RULE_V5) for q in v5.QUESTIONS["code_imports"])
    assert "(.Y, ..Y)" in v5.IMPORT_RULE_V5
    tree = v1.parse("from . import xyz\n")
    from hydra.training.grounded_corpus_v2 import imports_in_order
    assert imports_in_order(tree) == [".xyz"]
    assert v5.QUOTAS_V5["code_imports"] == 480


def test_import_traps_match_the_observed_failures():
    traps = v5.import_traps
    assert traps(v1.parse("from datetime import datetime\n"))
    assert traps(v1.parse("from math import radians, cos\n"))
    assert traps(v1.parse("from . import xyz\n"))
    assert traps(v1.parse("import numpy as np\n"))
    assert traps(v1.parse("import a\nimport b\nimport c\nimport d\nimport e\n"))
    assert traps(v1.parse("import foo.bar\n")) and traps(v1.parse("from foo.bar import baz\n"))
    assert traps(v1.parse("from .. import util\n"))
    assert not traps(v1.parse("import os\nimport sys\n"))


def test_sealed_holdout_documents_never_enter_the_corpus(tmp_path):
    from tests.test_grounded_corpus_v1 import boe_record

    boe = tmp_path / "boe.jsonl"
    boe.write_text("".join(json.dumps(boe_record(f"BOE-A-2099-{i}"), ensure_ascii=False) + "\n" for i in range(30)),
                   encoding="utf-8")
    code = tmp_path / "code.jsonl"
    code.write_text("", encoding="utf-8")
    holdout = tmp_path / "data" / "hydra-grounded-holdout-v9"
    holdout.mkdir(parents=True)
    (holdout / "holdout.jsonl").write_text(json.dumps({"provenance": {"document_id": "BOE-A-2099-3"}}) + "\n",
                                           encoding="utf-8")
    excluded = v5.sealed_holdout_ids(tmp_path / "data")
    assert excluded == {"BOE-A-2099-3"}
    v5.build(tmp_path / "out", boe, code, quotas=dict.fromkeys(v5.QUESTIONS, 3), exclude_ids=excluded)
    validate_corpus(tmp_path / "out")
    ids = {json.loads(line)["provenance"]["document_id"]
           for split in v1.SPLITS for line in (tmp_path / "out" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()}
    assert ids and "BOE-A-2099-3" not in ids


def test_v2_import_traps_are_kept_and_holdout_lookup_fails_closed(tmp_path):
    import pytest

    mixed = "import os\nfrom collections import deque\n\n\ndef f(x):\n    return os.sep + str(deque([x]))\n"
    record = {"id": "m", "text": mixed, "repo_name": "o/r", "path": "/m.py", "detected_licenses": ["MIT"]}
    _, traps = v5.code_candidates_v5(record, "nada")
    assert traps["imports"]  # v2 flagged plain + from imports; v5 must not drop it
    with pytest.raises(FileNotFoundError):
        v5.sealed_holdout_ids(tmp_path)
    assert v5.REPO_DATA.name == "data" and v5.REPO_DATA.parent == v5.Path(v5.__file__).resolve().parents[2]
