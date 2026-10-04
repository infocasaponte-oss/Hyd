import pytest

from hyd_calibrator.bounded_sentencepiece import BoundedSentencePiece


def test_same_ids_as_whole_document_including_indentation_unicode_and_unknowns(tmp_path):
    import sentencepiece as spm
    training = tmp_path / "training.txt"
    training.write_text("def exemplo():\n    return 'Texto en español café'\n" * 100, encoding="utf-8")
    spm.SentencePieceTrainer.train(input=str(training), model_prefix=str(tmp_path / "tok"), model_type="bpe",
                                 vocab_size=64, hard_vocab_limit=False, normalization_rule_name="identity",
                                 remove_extra_whitespaces=False, minloglevel=2, num_threads=1)
    processor = BoundedSentencePiece(tmp_path / "tok.model", span_chars=32)
    assert processor.supported
    text = ("def exemplo():\n    return 'Texto café'  \n\tUnicode \U0001f9ec \u0301\u2581  fin\n" * 10)
    ids = []
    for span in processor.spans(text):
        ids.extend(processor.pre_normalized.encode(span))
    assert ids == processor.original.encode(text)
    assert processor.count(text, 2) == len(ids)
    assert "".join(processor.spans(text)) == processor.original.normalize(text)


def test_unbounded_word_fails_closed(tmp_path):
    import sentencepiece as spm
    training = tmp_path / "training.txt"
    training.write_text("abc def abc def\n" * 10)
    spm.SentencePieceTrainer.train(input=str(training), model_prefix=str(tmp_path / "tok"), model_type="bpe",
                                 vocab_size=16, hard_vocab_limit=False, minloglevel=2, num_threads=1)
    processor = BoundedSentencePiece(tmp_path / "tok.model", span_chars=16)
    with pytest.raises(ValueError, match="safe tokenization budget"):
        processor.count("a" * 100, 2)
