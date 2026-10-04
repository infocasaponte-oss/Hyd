# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Professional quality filtering for the HYDRA Base pretraining corpus.

Applied by ``base_corpus.build`` after the licence policy and before deduplication:

1. **Text repair** (OCR sources): soft hyphens and zero-width characters, words hyphenated across
   line breaks, hard-wrapped lines joined back into paragraphs, page numbers and running headers.
2. **Language**: stopword evidence for the expected language(s) of each source.
3. **OCR noise**: share of words outside a reference lexicon of modern Spanish (built from the kept
   BOE texts) - catches garbled scans and long-s ("ſ" read as "f") orthography.
4. **Prose style** (Gopher rules, Rae et al. 2021): word count, mean word length, symbol/word
   ratio, alphabetic-word fraction, ellipsis and bullet lines.
5. **Repetition** (Gopher): duplicated lines/paragraphs and top / duplicated word n-gram character
   fractions.
6. **Code** (StarCoder-style): must parse as Python 3, no very long lines, enough alphanumerics, no
   auto-generated files, no embedded data blobs.
7. **Near-duplicates**: MinHash over word 5-gram shingles with LSH banding; a document whose
   estimated Jaccard similarity with an already kept one reaches ``NEAR_DUP_JACCARD`` is dropped.
8. **Decontamination**: documents used by HYDRA's evaluation sets (by BOE identifier) or sharing a
   13-word span with an evaluation question or answer are dropped.

Rules are per source kind (``RULES``) and were calibrated on 4,000 documents per source: Gopher's
repetition rules alone would reject ~92% of consolidated law, which is formulaic by nature.
Every rejection carries a reason name that ``base_corpus`` counts per source in the manifest.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import xxhash

# ---------------------------------------------------------------- 1. text repair (OCR)
_SOFT_HYPHEN = re.compile(chr(0x00AD) + r"[ \t]*\n?[ \t]*")  # "con<SHY> suelo" -> "consuelo"
_INVISIBLE = re.compile("[" + "".join(map(chr, (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))) + "]")
_HYPHEN_BREAK = re.compile(r"(\w)[-" + chr(0x2010) + chr(0x00AC) + r"]\n[ \t]*([a-záéíóúüñ])")
_PAGE_FURNITURE = re.compile(r"^\s*(?:[-–—]?\s*\d{1,4}\s*[-–—]?|[ivxlcdm]{1,7}\.?|p[áa]g(?:ina)?\.?\s*\d{1,4})\s*$",
                             re.I)
_SENTENCE_END = re.compile(r"[.!?:;»\")\]]$")


def repair_ocr(text: str) -> str:
    """Undo typesetting artefacts of scanned text without inventing content."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SOFT_HYPHEN.sub("", _INVISIBLE.sub("", text))
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    lines = text.split("\n")
    short = Counter(line.strip() for line in lines if 0 < len(line.strip()) < 60)
    # running headers/footers: short lines repeated on many pages of the same work
    headers = {line for line, n in short.items() if n >= 4 and n >= len(lines) / 400}
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped in headers or _PAGE_FURNITURE.match(stripped):
            continue
        if not stripped:
            if out and out[-1]:
                out.append("")
            continue
        # a hard-wrapped line continues the previous one when that one has no sentence end
        if out and out[-1] and not _SENTENCE_END.search(out[-1]) and stripped[0].islower():
            out[-1] = f"{out[-1]} {stripped}"
        else:
            out.append(stripped)
    return "\n".join(out).strip()


# ---------------------------------------------------------------- 2-5. prose
STOPWORDS = {
    "es": frozenset("de la que el en y a los del se las por un para con no una su al lo como más pero sus le ya o "
                    "este sí porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo "
                    "nos durante todos uno les ni contra otros ese eso ante ellos e esto mí antes algunos qué unos "
                    "yo otro otras otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas "
                    "algunas algo nosotros ser es son fue era han ha".split()),
    "en": frozenset("the be to of and a in that have i it for not on with he as you do at this but his by from they "
                    "we say her she or an will my one all would there their what so up out if about who get which "
                    "go me when make can like no just him know take into your some could them see other than then "
                    "now only its over also use how our is are was were been has".split()),
}
LANGUAGES = {"boe": ("es",), "pleias_parquet": ("es",), "acquisition": ("es", "en"), "stack_markdown": ("es", "en")}


@dataclass(frozen=True)
class ProseRules:
    min_words: int = 50
    max_words: int = 2_000_000
    min_stopword_ratio: float = 0.1
    max_oov: float | None = None  # OCR noise: share of words outside the reference lexicon
    style_checks: bool = True  # word length, symbols, alphabetic words, ellipsis and bullet lines
    mean_word: tuple[float, float] = (3.0, 10.0)
    max_symbol_ratio: float = 0.1
    min_alpha_words: float = 0.8
    max_ellipsis_lines: float = 0.3
    max_bullet_lines: float = 0.9
    line_repetition: bool = True  # duplicated lines (not for Markdown: code fences repeat by design)
    ngram_repetition: bool = True  # duplicated paragraphs and Gopher top / duplicated n-grams


RULES = {
    # calibrated on 6,000 book chunks: above 15% unknown words the scan is visibly broken (long s
    # read as f, letter-spaced words); this keeps ~71% of book chunks
    "pleias_parquet": ProseRules(max_oov=0.15),
    # Official consolidated law: formulaic by nature, with numbers, tables and dot leaders.
    # Only length, language and deduplication apply.
    "boe": ProseRules(min_stopword_ratio=0.08, style_checks=False, line_repetition=False, ngram_repetition=False),
    "acquisition": ProseRules(min_alpha_words=0.65, min_stopword_ratio=0.06, max_bullet_lines=0.95),
    # documentation: headings use '#', code blocks and lists are normal
    "stack_markdown": ProseRules(min_alpha_words=0.55, max_symbol_ratio=0.5, min_stopword_ratio=0.04,
                                 max_bullet_lines=0.95, line_repetition=False),
}
_BULLET = re.compile(r"^\s*(?:[-*•‣◦·]|\d+[.)])\s")
_ALPHA = re.compile(r"[^\W\d_]")
_PUNCT = ".,;:¡!¿?«»\"'()[]"
_FENCE = re.compile(r"^```.*?^```[^\n]*$", re.M | re.S)


def prose_problem(text: str, kind: str, lexicon: frozenset[str] | None = None) -> str | None:
    rules = RULES[kind]
    words = text.split()
    if len(words) < rules.min_words:
        return "too_few_words"
    if len(words) > rules.max_words:
        return "too_many_words"
    sample = words[:200_000]
    lowered = [w.lower().strip(_PUNCT) for w in sample]
    best = max(sum(w in STOPWORDS[lang] for w in lowered) for lang in LANGUAGES[kind])
    if best < 2 or best / len(lowered) < rules.min_stopword_ratio:
        return "language"
    if rules.max_oov is not None and lexicon is not None:
        if not lexicon:
            raise ValueError("OCR lexicon must not be empty")
        alphabetic = [w for w in lowered if w.isalpha()]
        if alphabetic and sum(w not in lexicon for w in alphabetic) / len(alphabetic) > rules.max_oov:
            return "ocr_noise"
    if rules.style_checks:
        problem = _style_problem(text, kind, rules, words, sample)
        if problem:
            return problem
    if kind == "stack_markdown":  # repeated code in examples is normal; repetition is judged on the prose
        prose = _FENCE.sub("", text)
        return repetition_problem(prose, prose.split()[:200_000], rules)
    return repetition_problem(text, sample, rules)


def _style_problem(text: str, kind: str, rules: ProseRules, words: list[str], sample: list[str]) -> str | None:
    mean = sum(map(len, sample)) / len(sample)
    if not rules.mean_word[0] <= mean <= rules.mean_word[1]:
        return "word_length"
    symbols = text.count("#") * (kind != "stack_markdown") + text.count("...") + text.count("…")
    if symbols / len(words) > rules.max_symbol_ratio:
        return "symbols"
    if sum(bool(_ALPHA.search(w)) for w in sample) / len(sample) < rules.min_alpha_words:
        return "non_alpha"
    lines = [line for line in text.split("\n") if line.strip()]
    if lines:
        if sum(line.rstrip().endswith(("...", "…")) for line in lines) / len(lines) > rules.max_ellipsis_lines:
            return "ellipsis_lines"
        if sum(bool(_BULLET.match(line)) for line in lines) / len(lines) > rules.max_bullet_lines:
            return "bullet_lines"
    return None


# Gopher repetition thresholds
_TOP_NGRAM = {2: 0.20, 3: 0.18, 4: 0.16}
_DUP_NGRAM = {5: 0.15, 6: 0.14, 7: 0.13, 8: 0.12, 9: 0.11, 10: 0.10}


def repetition_problem(text: str, words: list[str] | None = None, rules: ProseRules = ProseRules()) -> str | None:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if rules.line_repetition and len(lines) >= 5:
        counts = Counter(lines)
        dup = [line for line in lines if counts[line] > 1]
        if len(dup) / len(lines) > 0.3:
            return "dup_lines"
        if sum(map(len, dup)) / max(1, sum(map(len, lines))) > 0.2:
            return "dup_line_chars"
    if not rules.ngram_repetition:
        return None
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) >= 5:
        counts = Counter(paragraphs)
        dup = [p for p in paragraphs if counts[p] > 1]
        if len(dup) / len(paragraphs) > 0.3 or sum(map(len, dup)) / max(1, sum(map(len, paragraphs))) > 0.2:
            return "dup_paragraphs"
    words = (words or text.split())[:50_000]
    total = sum(map(len, words)) or 1
    for n, limit in _TOP_NGRAM.items():
        if len(words) < n * 10:
            break
        grams = Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1))
        gram, count = grams.most_common(1)[0]
        if count > 1 and count * sum(map(len, gram)) / total > limit:
            return f"top_{n}gram"
    lengths = np.fromiter(map(len, words), dtype=np.int64, count=len(words))
    for n, limit in _DUP_NGRAM.items():
        if len(words) < n * 10:
            break
        grams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
        counts = Counter(grams)
        covered = np.zeros(len(words) + 1, dtype=np.int64)
        for i, gram in enumerate(grams):
            if counts[gram] > 1:
                covered[i] += 1
                covered[i + n] -= 1
        if lengths[np.cumsum(covered[:-1]) > 0].sum() / total > limit:
            return f"dup_{n}gram"
    return None


def build_lexicon(texts: Iterable[str], min_count: int = 3, max_words: int = 300_000) -> frozenset[str]:
    """Reference vocabulary of modern Spanish (the kept BOE texts) for the OCR-noise rule."""
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(w for w in re.findall(r"[^\W\d_]+", text.lower()) if len(w) > 1)
    return frozenset(w for w, n in counts.most_common(max_words) if n >= min_count)


# ---------------------------------------------------------------- 6. code
_AUTOGEN = re.compile(r"auto-?generated|generated by|do not edit|automatically generated", re.I)
_BLOB = re.compile(r"[A-Za-z0-9+/=]{256,}|(?:\\x[0-9a-fA-F]{2}){64,}|(?:0x[0-9a-fA-F]{2},\s*){64,}")


def code_problem(text: str) -> str | None:
    if not text.strip():
        return "empty"
    lines = text.split("\n")
    if max(map(len, lines)) > 1000 or sum(map(len, lines)) / len(lines) > 100:
        return "long_lines"
    if sum(ch.isalnum() for ch in text) / len(text) < 0.25:
        return "non_alnum"
    if _AUTOGEN.search(text[:2000]):
        return "autogenerated"
    if _BLOB.search(text):
        return "data_blob"
    try:
        tree = ast.parse(text)
        compile(tree, "<corpus-validation>", "exec")  # validate only, never execute
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return "syntax"
    return None


def quality_problem(text: str, kind: str, lexicon: frozenset[str] | None = None) -> str | None:
    if kind == "stack_python":
        return code_problem(text)
    if kind == "stack_markdown":
        if max(map(len, text.split("\n"))) > 3000:
            return "long_lines"
        if _BLOB.search(text):
            return "data_blob"
    return prose_problem(text, kind, lexicon)


# ---------------------------------------------------------------- 7. near-duplicates (MinHash LSH)
NUM_PERM, BANDS = 112, 14  # 14 bands x 8 rows: candidate pairs from Jaccard ~0.72, verified below
NEAR_DUP_JACCARD = 0.8
SHINGLE = 5
MAX_SHINGLES = 50_000
_MERSENNE = np.uint64((1 << 61) - 1)
_rng = np.random.RandomState(20261003)
_A = _rng.randint(1, 1 << 31, NUM_PERM, dtype=np.int64).astype(np.uint64)
_B = _rng.randint(0, 1 << 31, NUM_PERM, dtype=np.int64).astype(np.uint64)


def minhash(text: str) -> np.ndarray:
    words = re.findall(r"\w+", text.lower())
    if len(words) < SHINGLE:
        words = words + [""] * (SHINGLE - len(words))
    hashes = np.fromiter((xxhash.xxh32_intdigest(" ".join(words[i:i + SHINGLE]).encode())
                          for i in range(len(words) - SHINGLE + 1)), dtype=np.uint64)
    hashes = np.unique(hashes)
    # (a*x + b) mod p with x < 2^32 and a, b < 2^31: the product stays below 2^63
    minimum = np.full(NUM_PERM, np.iinfo(np.uint64).max, dtype=np.uint64)
    for start in range(0, len(hashes), 4096):
        batch = hashes[start:start + 4096]
        minimum = np.minimum(minimum, ((np.outer(batch, _A) + _B) % _MERSENNE).min(axis=0))
    return minimum.astype(np.uint32)


@dataclass
class NearDuplicateIndex:
    bands: list[dict[int, int | list[int]]] = field(default_factory=lambda: [{} for _ in range(BANDS)])
    signatures: list[np.ndarray] = field(default_factory=list)

    def check_and_add(self, text: str) -> bool:
        """True when a kept document is a near-duplicate of text; otherwise text is indexed."""
        signature = minhash(text)
        rows = NUM_PERM // BANDS
        keys = [xxhash.xxh64_intdigest(signature[b * rows:(b + 1) * rows].tobytes()) for b in range(BANDS)]
        candidates = set()
        for band, key in zip(self.bands, keys):
            if key in band:
                bucket = band[key]
                candidates.update([bucket] if isinstance(bucket, int) else bucket)
        for index in candidates:
            if float(np.mean(self.signatures[index] == signature)) >= NEAR_DUP_JACCARD:
                return True
        position = len(self.signatures)
        self.signatures.append(signature)
        for band, key in zip(self.bands, keys):
            if key not in band:
                band[key] = position
            elif isinstance(band[key], int):
                band[key] = [band[key], position]
            else:
                band[key].append(position)
        return False


# ---------------------------------------------------------------- 8. decontamination
CONTAMINATION_NGRAM = 13
_BOE_ID = re.compile(r"BOE-[A-Z]-\d{4}-\d+")


@dataclass
class Contamination:
    """Evaluation material that must not be in pretraining data."""

    document_ids: set[str] = field(default_factory=set)
    ngrams: set[int] = field(default_factory=set)
    sources: list[str] = field(default_factory=list)
    source_sha256: dict[str, str] = field(default_factory=dict)

    def add_text(self, text: str, spans: bool = True) -> None:
        self.document_ids.update(_BOE_ID.findall(text))
        if not spans:
            return
        words = re.findall(r"\w+", text.lower())
        for i in range(len(words) - CONTAMINATION_NGRAM + 1):
            self.ngrams.add(xxhash.xxh64_intdigest(" ".join(words[i:i + CONTAMINATION_NGRAM]).encode()))

    def problem(self, text: str, document_id: str) -> str | None:
        if document_id in self.document_ids:
            return "eval_document"
        if self.ngrams:
            words = re.findall(r"\w+", text.lower())
            for i in range(len(words) - CONTAMINATION_NGRAM + 1):
                if xxhash.xxh64_intdigest(" ".join(words[i:i + CONTAMINATION_NGRAM]).encode()) in self.ngrams:
                    return "eval_overlap"
        return None

    @classmethod
    def from_paths(cls, paths: Iterable[Path]) -> Contamination:
        """Every evaluation file must exist: a missing one would silently weaken decontamination."""
        found = cls()
        for path in paths:
            data = path.read_bytes()
            raw = data.decode("utf-8-sig")
            found.source_sha256[path.as_posix()] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
            records = [json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix == ".jsonl" \
                else [json.loads(raw)]
            for record in records:
                found.document_ids.update(_provenance_ids(record))
                if isinstance(record, dict) and "messages" in record:
                    # The system message is the evaluated BOE source: that document is excluded by its
                    # identifier, while its legal boilerplate must not knock out unrelated laws.
                    for text in _strings(record):
                        found.add_text(text, spans=False)
                    for message in record["messages"]:
                        if message.get("role") != "system":
                            found.add_text(message.get("content") or "")
                else:
                    for text in _strings(record):
                        found.add_text(text)
            found.sources.append(path.as_posix())
        return found


def _provenance_ids(value) -> set[str]:
    """Capture explicit held-out source IDs, including Stack."""
    if isinstance(value, dict):
        ids = {value["document_id"]} if isinstance(value.get("document_id"), str) and value["document_id"] else set()
        for child in value.values():
            ids.update(_provenance_ids(child))
        return ids
    if isinstance(value, list):
        return set().union(*(_provenance_ids(child) for child in value))
    return set()


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


DEFAULT_EVALUATION_SETS = (
    "data/hydra-grounded-holdout-v1/holdout.jsonl",
    "data/hydra-grounded-holdout-v2/holdout.jsonl",
    "data/private/grounded-holdout-v2-wordings.json",
    "data/external-evaluation-v1/cases.json",
    "data/external-evaluation-v2/cases.json",
)
