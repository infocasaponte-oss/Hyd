# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import gzip
import hashlib
import json

import pytest

from hyd_calibrator.acquisition_snapshot import file_hash
from hyd_calibrator.corpus_census import census, signals


def fixture(tmp_path):
    spm = pytest.importorskip("sentencepiece")
    training = tmp_path / "training.txt"
    training.write_text("Corpus real para probar tokens.\nTextos distintos en castelán.\n" * 10, encoding="utf-8")
    spm.SentencePieceTrainer.train(input=str(training), model_prefix=str(tmp_path / "tok"), vocab_size=32,
                                 hard_vocab_limit=False, minloglevel=2, num_threads=1)
    model = tmp_path / "tok.model"
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    counts, hashes = {}, {}
    for name, texts in [("candidates", ["Texto único.", ""]), ("duplicates", ["Texto único."]),
                        ("review", ["Revisión de correo: a@example.org"] )]:
        counts[name] = len(texts)
        path = snapshot / f"{name}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            for text in texts:
                row = {"text": text, "source": "fixture", "source_revision": "a" * 40,
                       "category": "test", "language": "es", "license": "CC-BY",
                       "url": "https://example.org/fixture"}
                stream.write(json.dumps({"format": "hyd-acquisition-candidate/1", "bucket": name, "original": row,
                                         "verbatim_text_sha256": hashlib.sha256(text.encode()).hexdigest()}) + "\n")
        hashes[name] = file_hash(path)
    (snapshot / "manifest.json").write_text(json.dumps({"format": "hyd-acquisition-snapshot/1", "complete": True,
                                                        "output_sha256": hashes, "counts": counts}), encoding="utf-8")
    return snapshot, model, spm.SentencePieceProcessor(model_file=str(model))


def test_exact_tokens_special_tokens_and_no_automatic_rights(tmp_path):
    snapshot, model, sp = fixture(tmp_path)
    report = census(snapshot, model, tmp_path / "out", batch_chars=1)
    assert report["complete"] is True and report["training_allowed"] is False
    bucket = report["buckets"]["candidates"]
    assert bucket["content_tokens"] == len(sp.encode("Texto único."))
    assert bucket["pretraining_tokens_with_bos_eos"] == bucket["content_tokens"] + 4
    assert bucket["tokens_with_eos_only"] == bucket["content_tokens"] + 1
    assert report["review_signals"]["email_pattern_requires_privacy_review"] == 1
    assert report["review_signals"]["unversioned_license_declaration"] == 4
    review = json.loads((tmp_path / "out" / "source-rights-review.json").read_text())
    assert len(review["sources"]) == 1 and review["sources"][0]["lawful_access"] == "unknown"
    with pytest.raises(ValueError, match="new census"):
        census(snapshot, model, tmp_path / "out")


def test_modified_snapshot_rejected_before_output(tmp_path):
    snapshot, model, _ = fixture(tmp_path)
    with (snapshot / "review.jsonl.gz").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        census(snapshot, model, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_tampered_text_not_approved(tmp_path):
    snapshot, model, _ = fixture(tmp_path)
    path = snapshot / "review.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        row = json.loads(stream.readline())
    row["original"]["text"] = "changed text"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    manifest["output_sha256"]["review"] = file_hash(path)
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="text hash mismatch"):
        census(snapshot, model, tmp_path / "out")
    assert not (tmp_path / "out" / "report.json").exists()


def test_origin_placeholder_and_malformed_url():
    assert "placeholder_origin_identifier" in signals({"text": "", "license": "CC0-1.0",
                                                       "url": "https://eur-lex.europa.eu/?uri=CELEX:None"})
    assert "missing_or_invalid_origin_url" in signals({"text": "", "url": "https://[", "license": "CC0-1.0"})


def test_transient_windows_reader_lock_does_not_abort_census(tmp_path, monkeypatch):
    snapshot, model, _ = fixture(tmp_path)
    import hyd_calibrator.corpus_census as module
    original_write = module.write_text_atomic
    denied = 0

    def transient(path, text):
        nonlocal denied
        if path.name == "progress.json" and denied < 2:
            denied += 1
            raise PermissionError("temporary reader lock")
        return original_write(path, text)

    monkeypatch.setattr(module, "write_text_atomic", transient)
    assert census(snapshot, model, tmp_path / "out")["complete"] is True
    assert denied == 2


def test_budget_failure_is_reported_not_counted_as_zero_tokens(tmp_path):
    snapshot, model, sp = fixture(tmp_path)

    class BudgetProcessor:
        def bos_id(self):
            return sp.bos_id()

        def eos_id(self):
            return sp.eos_id()

        def vocab_size(self):
            return sp.vocab_size()

        def encode(self, *args, **kwargs):
            raise ValueError("normalized word/whitespace span exceeds safe tokenization budget")

    report = census(snapshot, model, tmp_path / "out", processor=BudgetProcessor())
    assert report["complete"] is True and report["token_count_complete"] is False
    assert report["buckets"]["candidates"]["unmeasured_rows"] == 2
    assert len(report["unmeasured_records"]) == 4
    assert all("text" not in item and len(item["verbatim_text_sha256"]) == 64
               for item in report["unmeasured_records"])
    assert report["training_allowed"] is False
