# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA Base tokenizer: SentencePiece BPE trained only on the clean, licence-checked corpus.

SentencePiece (``tokenizer.model``) is what llama.cpp's converter reads first for Llama-architecture
models, so the GGUF path needs no custom pre-tokenizer registration. Byte fallback means no input
is ever out of vocabulary; digits are split; chat markers are reserved as single tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from hydra.training.base_corpus import canonical_sha256, iter_texts

VOCAB_SIZE = 32_000
CHAT_TOKENS = ["<|im_start|>", "<|im_end|>", "<|fim_prefix|>", "<|fim_middle|>", "<|fim_suffix|>"]


def write_training_sample(corpus: Path, target: Path, max_chars: int, seed: int = 1234) -> dict:
    """Reservoir-free deterministic sample: keep each document with probability that fits max_chars."""
    if max_chars <= 0:
        raise ValueError("tokenizer sample budget must be positive")
    corpus_manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    # Final manifests already count characters; avoid an extra traversal of gigabytes.
    total = corpus_manifest.get("totals", {}).get("characters") or sum(len(t) for t in iter_texts(corpus))
    keep = min(1.0, max_chars / max(1, total))
    rng = random.Random(seed)
    written = docs = 0
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for text in iter_texts(corpus):
            if rng.random() <= keep:
                # one sentence-like line per line keeps SentencePiece's line length bounded
                before = written
                for line in text.split("\n"):
                    if line.strip():
                        remaining = max_chars - written
                        if remaining <= 1:
                            break
                        snippet = line[:min(4000, remaining - 1)] + "\n"
                        stream.write(snippet)
                        written += len(snippet)
                docs += int(written > before)
            if written >= max_chars - 1:
                break
    return {"corpus_characters": total, "sample_characters": written, "sample_documents": docs, "keep": keep}


def train(corpus: Path, output: Path, vocab_size: int = VOCAB_SIZE, max_chars: int = 200_000_000) -> dict:
    import sentencepiece as spm

    if output.exists():
        raise FileExistsError("use a new versioned tokenizer directory")
    output.mkdir(parents=True)
    sample = output / "training-sample.txt"
    stats = write_training_sample(corpus, sample, max_chars)
    spm.SentencePieceTrainer.train(
        input=str(sample), model_prefix=str(output / "tokenizer"), model_type="bpe", vocab_size=vocab_size,
        byte_fallback=True, split_digits=True, character_coverage=0.9999, normalization_rule_name="identity",
        remove_extra_whitespaces=False, add_dummy_prefix=True, allow_whitespace_only_pieces=True,
        user_defined_symbols=CHAT_TOKENS, unk_id=0, bos_id=1, eos_id=2, pad_id=3,
        max_sentence_length=8192, input_sentence_size=8_000_000, shuffle_input_sentence=True,
        num_threads=8, train_extremely_large_corpus=False,
    )
    sample.unlink()
    model = output / "tokenizer.model"
    manifest = {"kind": "sentencepiece-bpe", "vocab_size": vocab_size, "chat_tokens": CHAT_TOKENS,
                "special": {"unk": 0, "bos": 1, "eos": 2, "pad": 3}, "byte_fallback": True,
                "corpus_manifest_sha256": canonical_sha256(corpus / "manifest.json"),
                "tokenizer_model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(), **stats}
    write_hf_files(output)
    (output / "tokenizer-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def write_hf_files(folder: Path) -> None:
    """Hugging Face tokenizer files so transformers and the GGUF converter read the same vocabulary."""
    from transformers import LlamaTokenizer

    tok = LlamaTokenizer(vocab_file=str(folder / "tokenizer.model"), legacy=False, add_bos_token=True,
                         add_eos_token=False, pad_token="<pad>")
    tok.add_special_tokens({"additional_special_tokens": CHAT_TOKENS})
    tok.save_pretrained(str(folder))


def fertility(texts: list[str], encode) -> float:
    """Tokens per whitespace word: lower is a more efficient tokenizer."""
    words = sum(len(t.split()) for t in texts)
    return sum(len(encode(t)) for t in texts) / max(1, words)


def compare(tokenizer_dir: Path, corpus: Path, reference: Path, sample_docs: int = 400) -> dict:
    import sentencepiece as spm
    from tokenizers import Tokenizer

    ours = spm.SentencePieceProcessor(model_file=str(tokenizer_dir / "tokenizer.model"))
    theirs = Tokenizer.from_file(str(reference))
    by_kind: dict[str, list[str]] = {"legal_es": [], "code": []}
    for text in iter_texts(corpus, "validation"):
        kind = "code" if ("def " in text or "```" in text or "import " in text) else "legal_es"
        if len(by_kind[kind]) < sample_docs:
            by_kind[kind].append(text[:5000])
    return {kind: {"documents": len(texts),
                   "hydra_tokens_per_word": round(fertility(texts, lambda t: ours.encode(t)), 3),
                   "reference_tokens_per_word": round(fertility(texts, lambda t: theirs.encode(t).ids), 3)}
            for kind, texts in by_kind.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("data/hydra-base-corpus-v0"))
    parser.add_argument("--output", type=Path, default=Path("models/hydra-base-tokenizer-v0"))
    parser.add_argument("--vocab-size", type=int, default=VOCAB_SIZE)
    parser.add_argument("--reference", type=Path, default=Path("models/hydra-instruction-v7/merged/tokenizer.json"))
    args = parser.parse_args()
    result = train(args.corpus, args.output, args.vocab_size)
    result["comparison"] = compare(args.output, args.corpus, args.reference)
    (args.output / "tokenizer-manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8",
                                                         newline="\n")
    print(json.dumps(result, indent=2))
