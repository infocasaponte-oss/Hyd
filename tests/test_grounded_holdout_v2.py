# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.training import grounded_holdout_v2 as h2


def wordings(tmp_path):
    path = tmp_path / "private.json"
    path.write_text(json.dumps({family: f"Pregunta privada {i} sobre {{norm}} {{art}} {{sec}} {{name}}"
                                .replace(" {norm} {art} {sec} {name}", "") for i, family in enumerate(h2.QUOTAS)}),
                    encoding="utf-8")
    return path


def test_wordings_are_private_and_must_cover_every_family(tmp_path):
    path = wordings(tmp_path)
    loaded, digest = h2.load_wordings(path)
    assert set(loaded) == set(h2.QUOTAS) and len(digest) == 64
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"boe_heading": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        h2.load_wordings(partial)
    import inspect
    assert "¿" not in inspect.getsource(h2)  # no wording templates live in the repository


def test_exclusions_are_mandatory(tmp_path):
    with pytest.raises(ValueError):
        h2.build(tmp_path / "out", tmp_path / "b.jsonl", tmp_path / "c.jsonl", wordings(tmp_path), [], [tmp_path])
    with pytest.raises(ValueError):
        h2.build(tmp_path / "out", tmp_path / "b.jsonl", tmp_path / "c.jsonl", wordings(tmp_path), [tmp_path], [])


def test_underfilled_holdout_is_never_sealed(tmp_path):
    from tests.test_grounded_corpus_v1 import boe_record

    boe = tmp_path / "boe.jsonl"
    boe.write_text("".join(json.dumps(boe_record(f"BOE-A-2099-{i}"), ensure_ascii=False) + "\n" for i in range(5)),
                   encoding="utf-8")
    code = tmp_path / "code.jsonl"
    code.write_text("", encoding="utf-8")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    snapshot = tmp_path / "snap.jsonl"
    snapshot.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="underfilled"):
        h2.build(tmp_path / "out", boe, code, wordings(tmp_path), [corpus], [snapshot])
    assert not (tmp_path / "out").exists()


def test_helper_hashes_cover_generation_code():
    hashes = h2.helper_hashes()
    assert {"training/grounded_corpus_v1.py", "training/grounded_corpus_v2.py", "corpus/gates.py"} <= set(hashes)
    assert all(len(v) == 64 for v in hashes.values())
