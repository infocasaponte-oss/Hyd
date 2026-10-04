# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

OK = b"<response><status><code>200</code></status><data>"
END = b"</data></response>"


@pytest.fixture
def boe():
    path = Path(__file__).resolve().parents[1] / "scripts" / "download_boe_corpus.py"
    spec = importlib.util.spec_from_file_location("download_boe_corpus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requests_send_accept_header(boe):
    assert boe.HEADERS["Accept"] == "application/xml"


def test_status_wrapper_is_dropped_and_errors_raise(boe):
    assert boe.norm_text(OK + b"<texto><p>Primero.</p><p>Segundo.</p></texto>" + END) == "Primero.\nSegundo."
    with pytest.raises(ValueError):
        boe.norm_text(b"<response><status><code>404</code><text>No</text></status><data/></response>")


def test_version_in_force_on_download_date_is_kept(boe):
    xml = """<response><status><code>200</code></status><data><texto>
      <bloque id="a1"><version fecha_vigencia="20200101"><p>Vigente.</p></version>
                      <version fecha_vigencia="20990101"><p>Futura.</p></version></bloque>
      <bloque id="a2"><version fecha_vigencia="20990101"><p>Aún no vigente.</p></version></bloque>
      <bloque id="a3"><version><p>Sin fecha.</p></version></bloque>
    </texto></data></response>""".encode("utf-8")
    assert boe.norm_text(xml, today="20261002") == "Vigente.\nSin fecha."
    assert boe.norm_text(xml, today="20990102") == "Futura.\nAún no vigente.\nSin fecha."


def test_nested_blocks_are_not_duplicated(boe):
    elem = ET.fromstring("<version><table><tr><td><p>Celda A</p></td><td><p>Celda B</p></td></tr></table>"
                         "<ul><li><p>Punto uno</p></li></ul><p>Final.</p></version>")
    assert boe.lines_of(elem) == ["Celda A | Celda B", "Punto uno", "Final."]


def test_metadata_is_flat(boe):
    xml = OK + "<metadatos><titulo>Ley X</titulo><rango codigo='1'>Ley</rango></metadatos>".encode() + END
    assert boe.norm_metadata(xml) == {"titulo": "Ley X", "rango": "Ley"}


def run(boe, monkeypatch, out_dir, body):
    meta = OK + b"<metadatos><titulo>Ley X</titulo></metadatos>" + END
    monkeypatch.setattr(boe, "list_ids", lambda limit, ctx: ["BOE-A-2099-1"])
    monkeypatch.setattr(boe, "fetch", lambda url, ctx=None: meta if url.endswith("metadatos") else body)
    monkeypatch.setattr(sys, "argv", ["download_boe_corpus.py", "--out-dir", str(out_dir), "--sleep", "0"])
    return boe.main()


def test_run_where_every_document_is_skipped_fails(boe, monkeypatch, tmp_path):
    assert run(boe, monkeypatch, tmp_path, OK + b"<texto><p>Corto.</p></texto>" + END) == 1


def test_previous_format_is_set_aside_and_resume_is_idempotent(boe, monkeypatch, tmp_path):
    (tmp_path / "boe_legislacion_consolidada.jsonl").write_text('{"text":"200 ok antiguo"}\n', encoding="utf-8")
    (tmp_path / "boe_state.json").write_text(json.dumps({"done": ["BOE-A-2099-1"]}), encoding="utf-8")
    body = OK + ("<texto><p>" + "Texto nuevo. " * 30 + "</p></texto>").encode() + END
    assert run(boe, monkeypatch, tmp_path, body) == 0
    rows = (tmp_path / "boe_legislacion_consolidada.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["text"].startswith("Texto nuevo.")
    assert json.loads((tmp_path / "boe_state.json").read_text(encoding="utf-8"))["format"] == boe.FORMAT
    assert len(list(tmp_path.glob("boe_legislacion_consolidada.legacy-*.jsonl"))) == 1
    assert run(boe, monkeypatch, tmp_path, body) == 0  # already complete: 0/0/0 is not an error
