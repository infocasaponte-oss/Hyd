# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import gzip
import json

import pytest

from hydra.training import base_corpus as bc

_STOP = ("de", "la", "que", "el", "en", "y", "los", "del", "se", "las", "por", "un", "para", "con", "una", "su")
_SYLLABLES = ("ca", "lo", "mi", "ra", "te", "so", "pu", "der", "ven", "gal", "tor", "mas", "nu", "fe", "bri", "on")


def prose(seed: int, sentences: int = 40) -> str:
    """Varied Spanish-like prose: real documents do not repeat their sentences, and the quality rules
    (Gopher repetition, language) know it."""
    import random
    rng = random.Random(seed)
    out = []
    for _ in range(sentences):
        words = [rng.choice(_STOP) if i % 2 else "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 3)))
                 for i in range(rng.randint(10, 16))]
        out.append(" ".join(words).capitalize() + ".")
    return " ".join(out)


LONG = "Artículo 1. Objeto.\n" + prose(1, 8)


def write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def test_policy_privacy_quality_and_dedup_filters(tmp_path):
    boe = tmp_path / "boe.jsonl"
    write(boe, [{"document_id": "BOE-A-1", "text": LONG}, {"document_id": "BOE-A-2", "text": LONG},  # duplicate
                {"document_id": "BOE-A-3", "text": "corto"}])
    code = tmp_path / "py.jsonl"
    body = "".join(f"def suma_{i}(a, b):\n    return a + b + {i}\n\n" for i in range(12))
    write(code, [{"id": "a", "text": body, "detected_licenses": ["MIT"]},
                 {"id": "b", "text": body + "# gpl\n", "detected_licenses": ["GPL-3.0"]},
                 {"id": "c", "text": body + "# key\nAWS_SECRET='AKIAABCDEFGHIJKLMNOP'\n", "detected_licenses": ["MIT"]},
                 {"id": "d", "text": body + "# none\n", "detected_licenses": []}])
    md = tmp_path / "md.jsonl"
    write(md, [{"url": "u1", "text": "# Guía\n" + prose(2, 12),
                "license": "MIT,Apache-2.0"}])
    sources = [bc.SourceSpec("BOE", boe, "boe", "https://www.boe.es/datosabiertos/"),
               bc.SourceSpec("Py", code, "stack_python", "https://example.org/py"),
               bc.SourceSpec("Md", md, "stack_markdown", "https://example.org/md")]
    report = bc.build(tmp_path / "out", sources)
    by_name = {s["name"]: s for s in report["sources"]}
    assert by_name["BOE"]["kept"] == 1 and by_name["BOE"]["rejected"] == {"duplicate": 1, "too_short": 1}
    assert by_name["Py"]["kept"] == 1 and by_name["Py"]["rejected"]["license"] == 2
    assert by_name["Py"]["rejected"].get("credential", 0) + by_name["Py"]["rejected"].get("personal_data", 0) == 1
    assert by_name["Md"]["kept"] == 1
    texts = list(bc.iter_texts(tmp_path / "out")) + list(bc.iter_texts(tmp_path / "out", "validation"))
    assert len(texts) == 3 and not any("AKIA" in t for t in texts)
    notice = (tmp_path / "out" / "THIRD_PARTY_DATA_NOTICE.txt").read_text(encoding="utf-8")
    assert "es-public-sector-reuse" in notice and "MIT" in notice and "Apache-2.0" in notice
    for name, entry in report["files"].items():
        assert entry["sha256"] == bc.file_sha256(tmp_path / "out" / name)
    with pytest.raises(FileExistsError):
        bc.build(tmp_path / "out", sources)


def test_quality_rules_and_partial_lines(tmp_path):
    assert bc.quality_problem("x" * 50) == "too_short"
    assert bc.quality_problem("\n".join(["misma línea repetida"] * 40)) == "repetitive"
    assert bc.quality_problem(LONG) is None
    growing = tmp_path / "g.jsonl"
    growing.write_bytes(b'{"text": "a"}\n{"text": "b')
    assert list(bc.read_rows(growing)) == [{"text": "a"}]
    shard = tmp_path / "s.jsonl.gz"
    with gzip.open(shard, "wt", encoding="utf-8") as stream:
        stream.write('{"text": "hola"}\n')
    assert bc.normalize("a\r\n\n\n\n\nb  \n") == "a\n\n\nb"


def test_full_document_privacy_attribution_and_reproducible_shards(tmp_path):
    code = tmp_path / "py.jsonl"
    filler = "".join(f"def f_{i}(x):\n    return x + {i}\n\n" for i in range(3000))  # > 50,000 characters
    rows = [{"id": "late-secret", "text": filler + "TOKEN = 'AKIAABCDEFGHIJKLMNOP'\n", "detected_licenses": ["MIT"],
             "repo_name": "o/r", "path": "/s.py"},
            {"id": "clean", "text": filler, "detected_licenses": ["MIT"], "repo_name": "o/r", "path": "/c.py",
             "revision_id": "abc"}]
    write(code, rows)
    sources = [bc.SourceSpec("Py", code, "stack_python", "https://example.org/py")]
    first = bc.build(tmp_path / "a", sources)
    assert first["sources"][0]["rejected"].get("credential") == 1 and first["sources"][0]["kept"] == 1
    assert first["attributions"]["records"] == 1
    with gzip.open(tmp_path / "a" / "THIRD_PARTY_ATTRIBUTIONS.jsonl.gz", "rt", encoding="utf-8") as stream:
        entry = json.loads(stream.readline())
    assert entry["repository"] == "o/r" and entry["path"] == "/c.py" and entry["license"] == "MIT"
    second = bc.build(tmp_path / "b", sources)
    assert first["files"] == second["files"]  # identical records -> identical gzip bytes
    assert first["sources"][0]["input_sha256"] == bc.snapshot(code)[1]


def test_ocr_cleaning_and_chunking():
    prose = "La presente obra trata de la historia de los puertos y de su comercio con las Indias. " * 40
    noisy = "\n".join(["_", "ja", "fe", ". ,.", "^ <g"] * 10) + "\n" + prose
    cleaned = bc.clean_ocr(noisy)
    assert cleaned and "ja\n" not in cleaned and "historia de los puertos" in cleaned
    assert bc.clean_ocr("\n".join(["x ^ ~ 7 /"] * 200)) is None  # mostly debris
    assert bc.clean_ocr("The quick brown fox jumps over the lazy dog again and again. " * 40) is None  # not Spanish
    chunks = bc.chunk_paragraphs("\n".join(["párrafo " * 50] * 100), size=2000)
    assert len(chunks) > 1 and all(len(c) <= 2500 for c in chunks)


def test_acquisition_licences_are_parsed_and_policy_checked(tmp_path):
    batch = tmp_path / "acq" / "2026-10-02-x-review-v1"
    batch.mkdir(parents=True)
    text = prose(3, 15)
    write(batch / "technical-clear.jsonl", [
        {"document_id": "a", "text": text, "license": "CC-BY-4.0", "source_url": "https://e.org/a",
         "attribution": "Autora A"},
        {"document_id": "b", "text": prose(4, 15), "license_declared": "PSF-2.0; examples 0BSD"},
        {"document_id": "c", "text": prose(5, 15), "license_declared": "MIT"}])
    assert bc.record_licenses("acquisition", {"license_declared": "PSF-2.0; examples 0BSD"}) == ["PSF-2.0", "0BSD"]
    report = bc.build(tmp_path / "out", [bc.SourceSpec("Acq", tmp_path / "acq", "acquisition", "x")])
    stats = report["sources"][0]
    assert stats["kept"] == 2 and stats["rejected"] == {"license": 1}  # PSF-2.0 is not on the list
    assert report["attributions"]["records"] == 2


def test_licence_expressions_keep_every_id_and_long_lines_are_chunked():
    assert bc.license_ids("GPL-3.0 OR MIT") == ["GPL-3.0", "MIT"]
    assert bc.license_ids("(Apache-2.0 AND MIT) WITH LLVM-exception") == ["Apache-2.0", "MIT", "LLVM-exception"]
    one_line = "palabra " * 5000  # 40,000 characters without a single newline
    chunks = bc.chunk_paragraphs(one_line, size=2000)
    assert len(chunks) > 10 and all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks).replace(" ", "") == one_line.replace(" ", "")


def test_acquisition_needs_a_batch_and_keeps_a_final_record_without_newline(tmp_path):
    (tmp_path / "acq").mkdir()
    with pytest.raises(ValueError, match="no reviewed acquisition batch"):
        bc.source_rows(bc.SourceSpec("Acq", tmp_path / "acq", "acquisition", "x"))
    batch = tmp_path / "acq" / "b1"
    batch.mkdir()
    (batch / "technical-clear.jsonl").write_bytes(b'{"text": "a"}\n{"text": "b"}')
    rows, _ = bc.source_rows(bc.SourceSpec("Acq", tmp_path / "acq", "acquisition", "x"))
    assert [r["text"] for r in rows] == ["a", "b"]
    (batch / "technical-clear.jsonl").write_bytes(b'{"text": "a"}\n{"text": "b')
    rows, _ = bc.source_rows(bc.SourceSpec("Acq", tmp_path / "acq", "acquisition", "x"))
    assert [r["text"] for r in rows] == ["a"]


def test_pleias_works_stay_in_one_split_count_once_and_honour_the_selection(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    folder = tmp_path / "pleias"
    folder.mkdir()
    def make_work(seed):  # paragraphs of varied prose, ~70,000 characters: several chunks per work
        return "\n".join(prose(seed * 1000 + j, 5) for j in range(120))

    files = {}
    for index, name in enumerate(["a.parquet", "b.parquet"]):
        pq.write_table(pa.table({"identifier": [f"w{index}-{i}" for i in range(6)], "title": ["t"] * 6,
                                 "text": [make_work(index * 10 + i) for i in range(6)]}),
                       folder / name)
        files[name] = {"bytes": 0, "sha256": bc.file_sha256(folder / name)}
    # a stale larger run left b.parquet in the manifest; the current selection is only the first file
    (folder / "manifest.json").write_text(json.dumps({"files": files, "selection": {"count": 1}}), encoding="utf-8")
    report = bc.build(tmp_path / "out", [bc.SourceSpec("PleIAs", folder, "pleias_parquet", "x")])
    stats = report["sources"][0]
    assert stats["rejected"] == {}, stats
    assert stats["read"] == 6 and stats["chunks"] > 6 and stats["kept"] == stats["chunks"]  # 6 works, many chunks
    splits = {}
    for split in ("train", "validation"):
        for shard in (tmp_path / "out").glob(f"{split}-*.jsonl.gz"):
            with gzip.open(shard, "rt", encoding="utf-8") as stream:
                for line in stream:
                    work = json.loads(line)["document_id"].split("#")[0]
                    splits.setdefault(work, set()).add(split)
    assert splits and all(len(s) == 1 for s in splits.values()) and all(w.startswith("w0-") for w in splits)
    (folder / "manifest.json").write_text(json.dumps({"files": files, "selection": {"count": 3}}), encoding="utf-8")
    with pytest.raises(ValueError, match="2 of 3"):
        bc.source_rows(bc.SourceSpec("PleIAs", folder, "pleias_parquet", "x"))


def test_over_long_pleias_names_use_the_short_local_file(tmp_path):
    import importlib.util
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    spec = importlib.util.spec_from_file_location("fetch", bc.Path(__file__).resolve().parents[1]
                                                  / "scripts/fetch_pleias_spanish_pd.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    long_name = "0211-0210-" + "memoria-de-los-trabajos-del-mapa-geologico-" * 6 + ".parquet"
    short = fetch.local_name(long_name)
    assert len(short) <= fetch.MAX_NAME and short.endswith(".parquet") and fetch.local_name("a.parquet") == "a.parquet"
    assert short == fetch.local_name(long_name)  # stable across runs, so resumes find the file
    folder = tmp_path / "pleias"
    folder.mkdir()
    text = "".join(f"Capítulo {chr(97 + j % 26)}{chr(97 + j // 26)} de la memoria del mapa geológico de la provincia.\n"
                   for j in range(400))
    pq.write_table(pa.table({"identifier": ["w"], "title": ["t"], "text": [text]}), folder / short)
    manifest = {"files": {long_name: {"bytes": 0, "sha256": bc.file_sha256(folder / short), "local": short}},
                "selection": {"count": 1}}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rows, _ = bc.source_rows(bc.SourceSpec("PleIAs", folder, "pleias_parquet", "x"))
    assert {r["split_key"] for r in rows} == {"w"}
