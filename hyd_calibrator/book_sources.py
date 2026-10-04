"""Bounded metadata discovery and per-edition review; no book contents acquired."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

from .atomic import write_text_atomic
from .downloader import NoRedirect

AGENT = "HYDRA-Corpus-Review/1"
ATOM = {"a": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/terms/"}


def pending_work(source, identifier, title, authors, **declarations):
    return {"format": "hyd-book-work-review/1", "source_id": source, "work_id": identifier,
            "title_declared": title, "authors_declared": authors, "declarations": declarations,
            "review_status": "pending", "reviewer": None, "territories": ["ES"],
            "asset_url": None, "edition_id": None, "license": None,
            "work_rights": "pending", "translation_rights": "pending", "edition_rights": "pending",
            "source_access": "pending", "tdm_reservations": "pending", "attribution": "pending",
            "privacy": "pending", "decontamination": "pending", "evidence": [],
            "training_allowed": False}


def parse_opds(raw, base_url, limit=20):
    decoded = raw.decode("utf-8-sig", errors="strict")
    if "\x00" in decoded or "<!DOCTYPE" in decoded.upper() or "<!ENTITY" in decoded.upper():
        raise ValueError("DTD/entity declarations not permitted")
    root = ET.fromstring(decoded)
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("Atom feed required")
    works = []
    for entry in root.findall("a:entry", ATOM)[:limit]:
        identifier = entry.findtext("a:id", namespaces=ATOM)
        if not identifier:
            continue
        links = []
        for link in entry.findall("a:link", ATOM):
            href = urljoin(base_url, link.get("href", ""))
            parsed = urlsplit(href)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
            links.append({"url": href, "rel": link.get("rel"), "type": link.get("type")})
        works.append(pending_work("textos-info", identifier, entry.findtext("a:title", namespaces=ATOM),
                                  [a.findtext("a:name", namespaces=ATOM) for a in entry.findall("a:author", ATOM)],
                                  rights=entry.findtext("a:rights", namespaces=ATOM),
                                  published=entry.findtext("a:published", namespaces=ATOM),
                                  updated=entry.findtext("a:updated", namespaces=ATOM), links=links))
    return works


def parse_openlibrary(raw, limit=20):
    payload = json.loads(raw)
    return [pending_work("openlibrary", row.get("key"), row.get("title"), row.get("author_name", []),
                         first_publish_year=row.get("first_publish_year"), edition_keys=row.get("edition_key", []),
                         archive_ids=row.get("ia", []), ebook_access=row.get("ebook_access"),
                         metadata_is_not_book_license=True)
            for row in payload.get("docs", [])[:limit] if row.get("key")]


def fetch_metadata(url, *, opener, max_bytes=2 * 1024 * 1024):
    request = Request(url, headers={"User-Agent": AGENT, "Accept-Encoding": "identity"})
    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("metadata requires full successful response")
        raw = response.read(max_bytes + 1)
        if not raw or len(raw) > max_bytes:
            raise ValueError("metadata byte budget exceeded or empty response")
    return raw


def discover(catalog_path, source_id, out, *, opener=None):
    out = Path(out)
    if out.exists():
        raise ValueError("choose a new metadata directory")
    catalog_raw = Path(catalog_path).read_bytes()
    catalog = json.loads(catalog_raw)
    if catalog.get("format") != "hyd-book-source-catalog/1":
        raise ValueError("book source catalog required")
    source = next((s for s in catalog["sources"] if s["id"] == source_id), None)
    if source_id not in ("textos-info", "openlibrary") or not source:
        raise ValueError("source requires manual work review; no automated harvesting")
    url = source["metadata_url"]
    host = {"textos-info": "www.textos.info", "openlibrary": "openlibrary.org"}[source_id]
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != host or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("official metadata host required")
    opener = opener or build_opener(NoRedirect())
    robots_url = f"https://{host}/robots.txt"
    # Unavailable robots fails closed; no assumption that absence of evidence grants access.
    robots_raw = fetch_metadata(robots_url, opener=opener, max_bytes=256 * 1024)
    robots = RobotFileParser(robots_url)
    robots.parse(robots_raw.decode("utf-8", errors="strict").splitlines())
    if not robots.can_fetch(AGENT, url):
        out.mkdir(parents=True)
        (out / "robots.txt").write_bytes(robots_raw)
        result = {"format": "hyd-book-discovery/1", "state": "blocked-by-robots", "source_id": source_id,
                  "metadata_url": url, "checked_at": datetime.now(timezone.utc).isoformat(), "rows": 0,
                  "catalog_sha256": hashlib.sha256(catalog_raw).hexdigest(),
                  "robots_sha256": hashlib.sha256(robots_raw).hexdigest(),
                  "book_content_downloaded": False, "training_allowed": False}
        write_text_atomic(out / "manifest.json", json.dumps(result, indent=2))
        return result
    raw = fetch_metadata(url, opener=opener)
    works = parse_opds(raw, url) if source_id == "textos-info" else parse_openlibrary(raw)
    out.mkdir(parents=True)
    (out / "metadata.raw").write_bytes(raw)
    (out / "robots.txt").write_bytes(robots_raw)
    with (out / "works-review.jsonl").open("w", encoding="utf-8") as stream:
        for work in works:
            stream.write(json.dumps(work, ensure_ascii=False) + "\n")
    result = {"format": "hyd-book-discovery/1", "state": "metadata-only", "source_id": source_id, "metadata_url": url,
              "checked_at": datetime.now(timezone.utc).isoformat(), "rows": len(works),
              "catalog_sha256": hashlib.sha256(catalog_raw).hexdigest(),
              "metadata_sha256": hashlib.sha256(raw).hexdigest(), "robots_sha256": hashlib.sha256(robots_raw).hexdigest(),
              "book_content_downloaded": False, "training_allowed": False,
              "limitations": ["Only one metadata page; no crawling or pagination.",
                              "Robots compliance does not establish copyright or TDM permission.",
                              "Declared dates/rights/access are not verified; each edition remains pending."]}
    write_text_atomic(out / "manifest.json", json.dumps(result, ensure_ascii=False, indent=2))
    return result
