# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Download BOE consolidated legislation (official OpenData API) for the HYDRA model factory.

Output (gitignored): ``data/sources/boe/boe_legislacion_consolidada.jsonl`` with one norm per
line, resumable through ``boe_state.json``. Only the official public API is used.

API notes (verified 2026-10-02):
- Without an ``Accept`` header every endpoint answers HTTP 400.
- Responses are wrapped in ``<response><status>…</status><data>…</data>``; only ``<data>`` is
  read, so texts do not start with "200 ok".
- ``/texto`` has several ``<version>`` per ``<bloque>`` once a norm is amended; the version in
  force on the download date is kept (a future ``fecha_vigencia`` is not in force yet).
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUT_DIR = Path("data/sources/boe")
BASE = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
HEADERS = {"User-Agent": "HYDRA-corpus/1.0", "Accept": "application/xml"}
# Bump when normalisation changes: output in another format is set aside, never mixed.
FORMAT = 2
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "titulo"}


def build_ssl_context(ca_bundle: str | None = None) -> ssl.SSLContext:
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch(url: str, ssl_context: ssl.SSLContext | None = None) -> bytes:
    with urlopen(Request(url, headers=HEADERS), timeout=60, context=ssl_context) as response:
        return response.read()


def text_of(elem: ET.Element) -> str:
    return " ".join("".join(elem.itertext()).split())


def data_of(xml_bytes: bytes) -> ET.Element:
    root = ET.fromstring(xml_bytes)
    code = root.findtext("status/code")
    if code is not None and code.strip() != "200":
        raise ValueError(f"BOE status {code.strip()}: {root.findtext('status/text')}")
    data = root.find("data")
    return data if data is not None else root


def list_ids(limit: int, ssl_context: ssl.SSLContext | None = None) -> list[str]:
    data = data_of(fetch(BASE + "?" + urlencode({"limit": limit if limit > 0 else -1}), ssl_context))
    seen: dict[str, None] = {}
    for elem in data.iter("identificador"):
        text = (elem.text or "").strip()
        if re.fullmatch(r"BOE-A-\d{4}-\d+", text):
            seen.setdefault(text, None)
    ids = list(seen)
    return ids[:limit] if limit > 0 else ids


def lines_of(elem: ET.Element) -> list[str]:
    """One paragraph per line. An emitted block already contains its descendants' text, so
    the walk does not descend into it (no duplicated <p> inside <tr>/<li>)."""
    out: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag in BLOCK_TAGS:
            cells = [c for c in node if c.tag in ("td", "th")] if node.tag == "tr" else []
            line = " | ".join(t for t in map(text_of, cells) if t) if cells else text_of(node)
            if line:
                out.append(line)
            return
        for child in node:
            walk(child)

    walk(elem)
    if not out and text_of(elem):
        out.append(text_of(elem))
    return out


def current_version(versions: list[ET.Element], today: str) -> ET.Element | None:
    """Version in force on ``today`` (YYYYMMDD); undated -> last; all future -> None."""
    dated = [v for v in versions if (v.get("fecha_vigencia") or "").isdigit()]
    if not dated:
        return versions[-1] if versions else None
    in_force = [v for v in dated if v.get("fecha_vigencia") <= today]
    if not in_force:
        return None
    latest = max(v.get("fecha_vigencia") for v in in_force)
    return [v for v in in_force if v.get("fecha_vigencia") == latest][-1]


def norm_text(xml_bytes: bytes, today: str | None = None) -> str:
    today = today or time.strftime("%Y%m%d")
    data = data_of(xml_bytes)
    blocks = list(data.iter("bloque"))
    if not blocks:
        return "\n".join(lines_of(data))
    lines: list[str] = []
    for block in blocks:
        versions = block.findall("version")
        if not versions:
            lines.extend(lines_of(block))
            continue
        version = current_version(versions, today)
        if version is not None:
            lines.extend(lines_of(version))
    return "\n".join(lines)


def norm_metadata(xml_bytes: bytes) -> dict[str, str]:
    data = data_of(xml_bytes)
    meta = data.find("metadatos")
    if meta is None:
        meta = data
    return {child.tag: text_of(child) for child in meta if len(child) == 0 and text_of(child)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="0 = every available norm")
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--ca-bundle", default=None, help="PEM CA bundle; defaults to certifi when installed")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "boe_legislacion_consolidada.jsonl"
    state = args.out_dir / "boe_state.json"
    done: set[str] = set()
    saved: dict = {}
    if state.exists():
        try:
            saved = json.loads(state.read_text(encoding="utf-8"))
        except Exception:
            pass
    if saved.get("format") == FORMAT:
        done = set(saved.get("done", []))
    elif out.exists() or state.exists():
        stamp = time.strftime("%Y%m%dT%H%M%S")
        for path in (out, state):
            if path.exists():
                legacy = path.with_name(f"{path.stem}.legacy-{stamp}{path.suffix}")
                path.replace(legacy)
                print(f"previous format set aside: {legacy}")
    ssl_context = build_ssl_context(args.ca_bundle)
    ids = list_ids(args.limit, ssl_context)
    print(f"{len(ids)} norms listed, {len(done & set(ids))} already downloaded")
    written = skipped = errors = 0
    today = time.strftime("%Y%m%d")
    with out.open("a", encoding="utf-8", newline="\n") as stream:
        for i, boe_id in enumerate(ids, 1):
            if boe_id in done:
                continue
            try:
                meta = norm_metadata(fetch(f"{BASE}/id/{boe_id}/metadatos", ssl_context))
                body = norm_text(fetch(f"{BASE}/id/{boe_id}/texto", ssl_context), today)
                if len(body) < 200:
                    skipped += 1
                    continue
                row = {
                    "text": body, "source": "boe_legislacion_consolidada", "document_id": boe_id,
                    "title": meta.get("titulo"), "rank": meta.get("rango"),
                    "date_published": meta.get("fecha_publicacion"),
                    "date_updated": meta.get("fecha_actualizacion"), "text_in_force_on": today,
                    "repealed": meta.get("estatus_derogacion") == "S", "metadata": meta,
                    "jurisdiction": "ES", "document_type": "legislation", "language": "es",
                    "official_source": True, "license": "BOE datos abiertos (reutilización con cita da fonte)",
                }
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                done.add(boe_id)
                written += 1
                state.write_text(json.dumps({"format": FORMAT, "done": sorted(done)}, ensure_ascii=False),
                                 encoding="utf-8")
                print(f"[{i}/{len(ids)}] {boe_id}")
                time.sleep(args.sleep)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                errors += 1
                print(f"[WARN] {boe_id}: {exc}")
    print(f"written={written} skipped_short={skipped} errors={errors} -> {out}")
    if (errors or skipped) and not written:
        # "Everything already downloaded" (0/0/0) is fine; "attempted and nothing usable" is not.
        print("ERROR: no norm downloaded; see the warnings above.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
