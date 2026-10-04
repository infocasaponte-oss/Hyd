# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Clean pretraining corpus for HYDRA Base (proprietary weights).

Every document passes, in order: licence policy (``base_data_policy``, per record), basic quality
(length, mostly-printable, not dominated by repeated lines), the professional quality rules of
``base_quality`` (language, OCR noise, Gopher style and repetition, code checks), the privacy gate
(credentials and personal contact data are dropped), decontamination against HYDRA's evaluation
sets, exact deduplication of the normalised text and MinHash near-deduplication. Output is a set
of gzipped JSONL shards plus a manifest with per-source counts, rejections by reason, the rules and
thresholds applied, sha256 of every input, lexicon, evaluation set and shard, the hold-out split
and the third-party attribution notice for a release.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from hydra.corpus.gates import PrivacyGate
from hydra.core.atomic import write_text_atomic
from hydra.training import base_quality
from hydra.training.base_data_policy import admit_record, attribution_notice

MIN_CHARS = 200
SHARD_DOCS = 20_000
HOLDOUT_PERCENT = 1  # documents whose hash bucket is < 1 go to validation (perplexity)


@dataclass(frozen=True)
class SourceSpec:
    name: str
    path: Path
    kind: str  # "boe" | "stack_python" | "stack_markdown" | "pleias_parquet" | "acquisition"
    url: str


def stage1_sources(root: Path = Path("data/sources")) -> list[SourceSpec]:
    """Stage 1 adds Spanish public-domain books/newspapers and the reviewed acquisition batches."""
    return default_sources(root) + [
        SourceSpec("PleIAs Spanish-PD-Books", root / "pleias/spanish-pd-books", "pleias_parquet",
                   "https://huggingface.co/datasets/PleIAs/Spanish-PD-Books"),
        SourceSpec("PleIAs Spanish-PD-Newspapers", root / "pleias/spanish-pd-newspapers", "pleias_parquet",
                   "https://huggingface.co/datasets/PleIAs/Spanish-PD-Newspapers"),
        SourceSpec("Acquisition batches (technical-clear)", root / "acquisition", "acquisition",
                   "data/sources/acquisition"),
    ]


def default_sources(root: Path = Path("data/sources")) -> list[SourceSpec]:
    return [
        SourceSpec("BOE legislación consolidada", root / "boe/boe_legislacion_consolidada.jsonl", "boe",
                   "https://www.boe.es/datosabiertos/"),
        SourceSpec("Stack v2 edu (Python, permissive)", root / "code/stackv2_edu_python_sample.jsonl", "stack_python",
                   "https://huggingface.co/datasets/common-pile/stackv2_edu_filtered"),
        SourceSpec("Stack v2 edu (Markdown, permissive)", root / "code/stackv2_edu_markdown_sample.jsonl",
                   "stack_markdown", "https://huggingface.co/datasets/common-pile/stackv2_edu_filtered"),
    ]


def record_licenses(kind: str, row: dict) -> list[str]:
    if kind == "boe":
        return ["es-public-sector-reuse"]  # BOE datos abiertos: reutilización con cita de la fuente
    if kind == "stack_python":
        return list(row.get("detected_licenses") or [])
    if kind == "stack_markdown":  # fetcher rows carry detected_licenses; older rows a "license" string
        if row.get("detected_licenses"):
            return list(row["detected_licenses"])
        return [lic.strip() for lic in str(row.get("license") or "").split(",") if lic.strip()]
    if kind == "pleias_parquet":
        return ["public-domain"]  # collection declares public domain in all regions (EU art. 14)
    if kind == "acquisition":
        # "license" (CC-BY-4.0) or "license_declared" ("PSF-2.0; examples 0BSD"): every part must pass
        declared = str(row.get("license") or row.get("license_declared") or "")
        return license_ids(declared)
    raise ValueError(f"unknown source kind {kind}")


LICENSE_OPERATORS = frozenset({"OR", "AND", "WITH"})


def license_ids(declared: str) -> list[str]:
    """Every licence id in a declaration ("GPL-3.0 OR MIT" -> both, so the copyleft one is still
    checked). Lowercase qualifier words ("examples", "docs") are not ids; ids carry a capital or a digit."""
    tokens = re.split(r"[;,()\s]+", declared)
    return [t for t in tokens if t and t.upper() not in LICENSE_OPERATORS
            and (t == "public-domain" or any(c.isupper() or c.isdigit() for c in t))]


def record_attribution(kind: str, row: dict, licenses: str) -> dict | None:
    """Per-file attribution kept for permissive code/docs (MIT/Apache/BSD notices name the work)."""
    if kind in ("boe", "pleias_parquet"):
        return None
    if kind == "acquisition":
        return {"url": row.get("source_url"), "attribution": row.get("attribution"),
                "license_evidence": row.get("license_evidence"), "license": licenses}
    return {"repository": row.get("repo_name"), "path": row.get("path"), "url": row.get("url"),
            "revision": row.get("revision_id"), "license": licenses}


def document_id(kind: str, row: dict) -> str:
    if kind in ("boe", "pleias_parquet"):
        return row["document_id"]
    if kind == "acquisition":
        return str(row.get("document_id") or f"{row.get('source_url')}#{row.get('page', '')}")
    return str(row.get("id") or row.get("url") or row.get("path") or "")


SPANISH_STOPWORDS = frozenset("de la que el en y a los del se las por un para con no una su al lo como más "
                              "pero sus le ya o este sí porque esta entre cuando muy sin sobre".split())


def clean_ocr(text: str, min_line: int = 25, min_letters: float = 0.7) -> str | None:
    """Drop OCR debris lines (stamps, page furniture, garbage) from scanned public-domain text.

    Returns None when most of the document is debris or it no longer reads as Spanish prose.
    """
    lines, kept_chars, total_chars = [], 0, 0
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1]:
                lines.append("")
            continue
        total_chars += len(stripped)
        letters = sum(ch.isalpha() for ch in stripped)
        if len(stripped) >= min_line and letters / len(stripped) >= min_letters:
            lines.append(stripped)
            kept_chars += len(stripped)
    if not total_chars or kept_chars / total_chars < 0.5:
        return None
    cleaned = "\n".join(lines).strip()
    words = re.findall(r"[a-záéíóúüñ]+", cleaned[:50_000].lower())
    if len(words) < 50 or sum(w in SPANISH_STOPWORDS for w in words) / len(words) < 0.18:
        return None
    return cleaned


def chunk_paragraphs(text: str, size: int = 16_000) -> list[str]:
    """Split long works at paragraph/line boundaries into ~size-character segments."""
    chunks, current = [], []
    length = 0
    for paragraph in _bounded_lines(text, size):
        if length + len(paragraph) > size and current:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(paragraph)
        length += len(paragraph) + 1
    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]


def _bounded_lines(text: str, size: int) -> Iterator[str]:
    """Lines no longer than size: a badly line-broken OCR line is cut at the last space before the limit."""
    for line in text.split("\n"):
        while len(line) > size:
            cut = line.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            yield line[:cut]
            line = line[cut:].lstrip(" ")
        yield line


def source_rows(spec: SourceSpec) -> tuple[Iterator[dict], str]:
    """Rows of one source and the sha256 that identifies exactly what is read."""
    if spec.kind == "pleias_parquet":
        return _pleias_rows(spec.path)
    if spec.kind == "acquisition":
        return _acquisition_rows(spec.path)
    data, digest = snapshot(spec.path)
    return (json.loads(raw) for raw in data.splitlines() if raw.strip()), digest


def _pleias_rows(folder: Path) -> tuple[Iterator[dict], str]:
    """Parquet files listed (and pinned by sha256 and revision) in the fetcher's manifest."""
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # The selection is a sorted prefix of the repository listing; a larger earlier run may have left
    # extra files in the manifest, so only the current prefix is read, and it must be complete.
    count = manifest["selection"]["count"]
    selected = sorted(manifest["files"])[:count]
    if len(selected) < count:
        raise ValueError(f"{folder}: {len(selected)} of {count} selected files downloaded")
    for name in selected:
        alias = manifest["files"][name].get("local", name)
        if not isinstance(alias, str) or not alias or Path(alias).name != alias or "\\" in alias or "/" in alias:
            raise ValueError("PleIAs local filename must remain inside its source directory")
        local = folder / alias
        if not local.resolve().is_relative_to(folder.resolve()):
            raise ValueError("PleIAs local file escapes its source directory")
        if file_sha256(local) != manifest["files"][name]["sha256"]:
            raise ValueError(f"{local} does not match its manifest")
    digest = hashlib.sha256(f"{canonical_sha256(manifest_path)}\n{json.dumps(selected)}".encode()).hexdigest()

    def rows():
        import pyarrow.parquet as pq

        for name in selected:
            parquet = pq.ParquetFile(folder / manifest["files"][name].get("local", name))
            for group in range(parquet.num_row_groups):
                for book in parquet.read_row_group(group, columns=["identifier", "title", "text"]).to_pylist():
                    cleaned = clean_ocr(base_quality.repair_ocr(book.get("text") or ""))
                    if cleaned is None:
                        yield {"document_id": f"{book['identifier']}#rejected", "text": "", "chunk": 0}
                        continue
                    for index, chunk in enumerate(chunk_paragraphs(cleaned)):
                        # split_key: every chunk of one work lands in the same split (no leakage)
                        yield {"document_id": f"{book['identifier']}#{index}", "title": book.get("title"),
                               "text": chunk, "chunk": index, "split_key": str(book["identifier"])}
    return rows(), digest


def _acquisition_rows(root: Path) -> tuple[Iterator[dict], str]:
    """technical-clear.jsonl of every reviewed batch; the digest covers each file's bytes."""
    files = sorted(root.glob("*/technical-clear.jsonl"))
    if not files:
        raise ValueError(f"no reviewed acquisition batch (*/technical-clear.jsonl) under {root}")
    digest = hashlib.sha256()
    snapshots = []
    for path in files:
        data, file_digest = snapshot_final(path)
        digest.update(f"{path.parent.name}/{path.name}:{file_digest}\n".encode())
        snapshots.append(data)
    return (json.loads(raw) for data in snapshots for raw in data.splitlines() if raw.strip()), digest.hexdigest()


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{4,}", "\n\n\n", text).strip()


def quality_problem(text: str) -> str | None:
    if len(text) < MIN_CHARS:
        return "too_short"
    sample = text[:20_000]
    if sum(ch.isprintable() or ch in "\n\t" for ch in sample) / len(sample) < 0.98:
        return "non_printable"
    lines = [line.strip() for line in sample.splitlines() if line.strip()]
    if len(lines) >= 20 and len(set(lines)) / len(lines) < 0.5:
        return "repetitive"
    return None


def holdout(doc_hash: str) -> bool:
    return int(doc_hash[:8], 16) % 100 < HOLDOUT_PERCENT


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot(path: Path) -> tuple[bytes, str]:
    """The exact complete-line bytes that will be parsed, and their sha256 (a source may be growing)."""
    data = path.read_bytes()
    data = data[:data.rfind(b"\n") + 1]
    return data, hashlib.sha256(data).hexdigest()


def snapshot_final(path: Path) -> tuple[bytes, str]:
    """Like snapshot, for finished files: a valid last record without a trailing newline is kept."""
    data = path.read_bytes()
    tail = data[data.rfind(b"\n") + 1:]
    if tail.strip():
        try:
            json.loads(tail)
            data += b"\n"
        except ValueError:
            data = data[:len(data) - len(tail)]
    return data, hashlib.sha256(data).hexdigest()


def read_rows(path: Path) -> Iterator[dict]:
    """Complete JSON lines only (a source may still be growing)."""
    data, _ = snapshot(path)
    for raw in data.splitlines():
        if raw.strip():
            yield json.loads(raw)


def scan_privacy(gate: PrivacyGate, text: str, chunk: int = 50_000, overlap: int = 512) -> tuple[bool, bool]:
    """Scan the whole document in overlapping chunks (secrets can sit anywhere in a long file)."""
    credential = pii = False
    for start in range(0, max(1, len(text)), chunk):
        _, found_credential, found_pii = gate.scan_text(text[max(0, start - overlap):start + chunk])
        credential, pii = credential or found_credential, pii or found_pii
        if credential:
            break
    return credential, pii


def gzip_text(path: Path):
    """Text gzip writer with a fixed header timestamp, so identical records give identical bytes."""
    return io.TextIOWrapper(gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0),
                            encoding="utf-8", newline="\n")


def canonical_sha256(path: Path) -> str:
    """Digest of a JSON/text artifact with LF endings, matching the repository's normalised copy."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class ShardWriter:
    def __init__(self, folder: Path, split: str) -> None:
        self.folder, self.split, self.index, self.count = folder, split, 0, 0
        self.stream = None
        self.files: dict[str, dict] = {}

    def write(self, record: dict) -> None:
        if self.stream is None or self.count >= SHARD_DOCS:
            self.close()
            name = f"{self.split}-{self.index:05d}.jsonl.gz"
            self.stream = gzip_text(self.folder / name)
            self.files[name] = {"documents": 0}
            self.index += 1
            self.count = 0
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.files[f"{self.split}-{self.index - 1:05d}.jsonl.gz"]["documents"] += 1
        self.count += 1

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def build(output: Path, sources: list[SourceSpec], contamination: base_quality.Contamination | None = None,
          lexicon: Path | None = None) -> dict:
    """``contamination`` and ``lexicon`` enable decontamination and the OCR-noise rule; the release
    CLI always passes both, unit tests may leave them out."""
    if output.exists():
        raise FileExistsError("use a new versioned corpus directory")
    words = frozenset(lexicon.read_text(encoding="utf-8").split()) if lexicon else None
    if lexicon is not None and not words:
        raise ValueError("release OCR lexicon must not be empty")
    output.mkdir(parents=True)
    gate = PrivacyGate(pseudonymize_persons=False)  # official texts name public officials by design
    seen: set[str] = set()
    near = base_quality.NearDuplicateIndex()
    writers = {"train": ShardWriter(output, "train"), "validation": ShardWriter(output, "validation")}
    report: dict = {"version": output.name, "sources": [], "totals": {"documents": 0, "characters": 0},
                    "filters": filter_report(contamination, lexicon)}
    generator_hash = canonical_sha256(Path(__file__))
    notice_sources = []
    attributions = gzip_text(output / "THIRD_PARTY_ATTRIBUTIONS.jsonl.gz")
    attribution_count = 0
    for spec in sources:
        rows, input_sha = source_rows(spec)  # the digest identifies exactly what is read
        stats = {"name": spec.name, "path": str(spec.path), "kind": spec.kind, "input_sha256": input_sha,
                 "read": 0, "kept": 0, "characters": 0, "rejected": {}}
        licenses_kept: set[str] = set()
        for row in rows:
            # "read" counts source works: a work split into chunks counts once (chunks counted apart)
            if row.get("chunk", 0) == 0:
                stats["read"] += 1
            if "chunk" in row:
                stats["chunks"] = stats.get("chunks", 0) + 1
            if spec.kind == "pleias_parquet" and row["document_id"].endswith("#rejected"):
                stats["rejected"]["ocr"] = stats["rejected"].get("ocr", 0) + 1
                continue
            decision = admit_record(record_licenses(spec.kind, row))
            reason = None if decision.allowed else "license"
            text = normalize(row.get("text") or "") if reason is None else ""
            if reason is None:
                reason = quality_problem(text)
            if reason is None:
                reason = base_quality.quality_problem(text, spec.kind, words)
            if reason is None:
                credential, pii = scan_privacy(gate, text)
                reason = "credential" if credential else "personal_data" if pii else None
            if reason is None and contamination is not None:
                reason = contamination.problem(text, document_id(spec.kind, row))
            doc_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if reason is None else ""
            if reason is None and doc_hash in seen:
                reason = "duplicate"
            if reason is None and near.check_and_add(text):
                reason = "near_duplicate"
            if reason is not None:
                stats["rejected"][reason] = stats["rejected"].get(reason, 0) + 1
                continue
            seen.add(doc_hash)
            licenses_kept.update(decision.license.split(", "))
            split_hash = hashlib.sha256(row["split_key"].encode()).hexdigest() if row.get("split_key") else doc_hash
            writers["validation" if holdout(split_hash) else "train"].write({
                "text": text, "source": spec.name, "document_id": document_id(spec.kind, row),
                "license": decision.license, "sha256": doc_hash})
            attribution = record_attribution(spec.kind, row, decision.license)
            if attribution is not None:
                attributions.write(json.dumps({"source": spec.name, "document_id": document_id(spec.kind, row),
                                               **attribution}, ensure_ascii=False) + "\n")
                attribution_count += 1
            stats["kept"] += 1
            stats["characters"] += len(text)
        report["sources"].append(stats)
        report["totals"]["documents"] += stats["kept"]
        report["totals"]["characters"] += stats["characters"]
        notice_sources += [{"name": spec.name, "license": lic, "url": spec.url} for lic in sorted(licenses_kept)]
    files = {}
    for writer in writers.values():
        writer.close()
        for name, entry in writer.files.items():
            files[name] = {**entry, "sha256": file_sha256(output / name)}
    attributions.close()
    report["files"] = files
    report["holdout_percent"] = HOLDOUT_PERCENT
    notice = attribution_notice(notice_sources) + (
        f"\nPer-file attribution (repository, path, revision, licence) for {attribution_count} retained "
        "code and documentation files: THIRD_PARTY_ATTRIBUTIONS.jsonl.gz\n")
    (output / "THIRD_PARTY_DATA_NOTICE.txt").write_text(notice, encoding="utf-8", newline="\n")
    report["notice_sha256"] = hashlib.sha256(notice.encode("utf-8")).hexdigest()
    report["attributions"] = {"file": "THIRD_PARTY_ATTRIBUTIONS.jsonl.gz", "records": attribution_count,
                              "sha256": file_sha256(output / "THIRD_PARTY_ATTRIBUTIONS.jsonl.gz")}
    if generator_hash != canonical_sha256(Path(__file__)) or report["filters"] != filter_report(contamination, lexicon):
        raise ValueError("quality configuration changed during construction; corpus cannot be sealed")
    if contamination is not None and any(canonical_sha256(Path(path)) != digest
                                         for path, digest in contamination.source_sha256.items()):
        raise ValueError("evaluation files changed during construction; corpus cannot be sealed")
    report["generator_sha256"] = generator_hash
    write_text_atomic(output / "manifest.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def filter_report(contamination: base_quality.Contamination | None, lexicon: Path | None) -> dict:
    from dataclasses import asdict

    return {
        "rules": {kind: asdict(rules) for kind, rules in base_quality.RULES.items()},
        "code": {"parse": "python3 ast", "max_line": 1000, "max_mean_line": 100, "min_alnum": 0.25,
                 "autogenerated": True, "data_blobs": True},
        "near_duplicates": {"method": "minhash-lsh", "shingle_words": base_quality.SHINGLE,
                            "permutations": base_quality.NUM_PERM, "bands": base_quality.BANDS,
                            "jaccard": base_quality.NEAR_DUP_JACCARD},
        "decontamination": None if contamination is None else {
            "ngram_words": base_quality.CONTAMINATION_NGRAM, "document_ids": len(contamination.document_ids),
            "ngrams": len(contamination.ngrams),
            "sets": dict(contamination.source_sha256)},
        "lexicon": None if lexicon is None else {"path": lexicon.as_posix(), "sha256": canonical_sha256(lexicon),
                                                 "words": len(lexicon.read_text(encoding="utf-8").split())},
        "quality_module_sha256": hashlib.sha256(
            Path(base_quality.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
    }


def write_lexicon(sources: list[SourceSpec], output: Path, boe_min: int = 3, ocr_min: int = 30) -> dict:
    """Frozen reference vocabulary for the OCR-noise rule: BOE words seen at least ``boe_min`` times
    plus words seen at least ``ocr_min`` times across the public-domain OCR text. OCR errors are rare
    and idiosyncratic, real words recur; the file's sha256 is pinned in every corpus manifest."""
    from collections import Counter

    if output.exists():
        raise FileExistsError("use a new versioned lexicon file")
    counts = {"boe": Counter(), "pleias_parquet": Counter()}
    inputs = {}
    for spec in sources:
        if spec.kind not in counts:
            continue
        rows, inputs[spec.name] = source_rows(spec)
        for row in rows:
            # Reference vocabulary must not learn from validation works either.
            if not admit_record(record_licenses(spec.kind, row)).allowed:
                continue
            split_key = row.get("split_key")
            text_hash = hashlib.sha256(normalize(row.get("text") or "").encode()).hexdigest()
            split_hash = hashlib.sha256(str(split_key).encode()).hexdigest() if split_key else text_hash
            if holdout(split_hash):
                continue
            counts[spec.kind].update(w for w in re.findall(r"[^\W\d_]+", (row.get("text") or "").lower())
                                     if len(w) > 1)
    words = sorted({w for w, n in counts["boe"].items() if n >= boe_min}
                   | {w for w, n in counts["pleias_parquet"].items() if n >= ocr_min})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(words) + "\n", encoding="utf-8", newline="\n")
    meta = {"words": len(words), "boe_min_count": boe_min, "ocr_min_count": ocr_min, "inputs_sha256": inputs,
            "partition": "train-only", "holdout_percent": HOLDOUT_PERCENT,
            "sha256": canonical_sha256(output)}
    output.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                           newline="\n")
    return meta


def iter_texts(corpus: Path, split: str = "train") -> Iterator[str]:
    for shard in sorted(corpus.glob(f"{split}-*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)["text"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/hydra-base-corpus-v0"))
    parser.add_argument("--sources-root", type=Path, default=Path("data/sources"))
    parser.add_argument("--stage", type=int, choices=(0, 1), default=0)
    parser.add_argument("--lexicon", type=Path, default=Path("data/sources/lexicon/hydra-es-lexicon-v1.txt"))
    parser.add_argument("--build-lexicon", action="store_true", help="write the frozen OCR lexicon and stop")
    parser.add_argument("--evaluation-sets", type=Path, nargs="*",
                        default=[Path(p) for p in base_quality.DEFAULT_EVALUATION_SETS])
    args = parser.parse_args()
    sources = stage1_sources(args.sources_root) if args.stage == 1 else default_sources(args.sources_root)
    if args.build_lexicon:
        print(json.dumps(write_lexicon(sources, args.lexicon), indent=2, ensure_ascii=False))
        raise SystemExit(0)
    summary = build(args.output, sources, base_quality.Contamination.from_paths(args.evaluation_sets),
                    args.lexicon if args.stage == 1 else None)
    print(json.dumps({k: summary[k] for k in ("totals", "sources")}, indent=2, ensure_ascii=False))
