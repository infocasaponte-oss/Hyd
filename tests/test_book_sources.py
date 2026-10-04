import hashlib
import io
import json

import pytest

from hyd_calibrator.book_sources import discover, parse_opds, parse_openlibrary
from hyd_calibrator.downloader import download_asset, validate_plan


def book_plan(tmp_path):
    evidence = tmp_path / "review.txt"
    evidence.write_text("Fixture human review of original, translation, edition and source terms.")
    review = {"format": "hyd-book-work-review/1", "source_id": "textos-info", "work_id": "fixture",
              "edition_id": "fixture-edition", "asset_url": "https://www.textos.info/fixture.epub",
              "license": "CC-BY-4.0", "review_status": "reviewed", "reviewer": {"kind": "human", "id": "fixture"},
              "territories": ["ES"], "training_allowed": False,
              "evidence": [{"path": "review.txt", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}]}
    for field in ("work_rights", "translation_rights", "edition_rights", "source_access", "tdm_reservations", "attribution"):
        review[field] = "reviewed"
    return {"format": "hyd-corpus-download-plan/2", "source_id": "textos-info", "asset_url": review["asset_url"],
            "rights": {"verified": True, "license": "CC-BY-4.0", "evidence_url": "https://www.textos.info/fixture"},
            "work_review": review, "training_allowed": False, "state": "prepared", "max_bytes": 1024}


class Opener:
    def __init__(self, bodies):
        self.bodies, self.calls = iter(bodies), []

    def open(self, request, timeout):
        self.calls.append(request.full_url)
        response = io.BytesIO(next(self.bodies))
        response.status = 200
        response.headers = {}
        return response


def test_book_requires_per_edition_review_and_evidence_before_network(tmp_path):
    plan = book_plan(tmp_path)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    opener = Opener([b"fixture asset"])
    (tmp_path / "review.txt").write_text("changed")
    with pytest.raises(ValueError, match="evidence files"):
        download_asset(path, tmp_path / "out", opener=opener)
    assert not opener.calls and not (tmp_path / "out").exists()


def test_verified_work_download_keeps_review_and_never_authorizes_training(tmp_path):
    plan = book_plan(tmp_path)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    result = download_asset(path, tmp_path / "out", opener=Opener([b"fixture asset"]))
    assert result["work_review"] == plan["work_review"] and result["training_allowed"] is False


@pytest.mark.parametrize("field", ["work_rights", "translation_rights", "edition_rights", "source_access", "tdm_reservations"])
def test_pending_work_axis_cannot_be_bypassed(tmp_path, field):
    plan = book_plan(tmp_path)
    plan["work_review"][field] = "pending"
    with pytest.raises(ValueError, match="pending"):
        validate_plan(plan)


def test_book_cannot_use_legacy_checkbox_or_openlibrary_borrowing(tmp_path):
    plan = book_plan(tmp_path)
    plan["format"] = "hyd-corpus-download-plan/1"
    plan.pop("work_review")
    with pytest.raises(ValueError, match="per-work"):
        validate_plan(plan)
    plan["source_id"] = "openlibrary"
    with pytest.raises(ValueError, match="not enabled"):
        validate_plan(plan)


def test_metadata_parsing_does_not_invent_rights_or_fetch_books():
    raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>id1</id><title>Fixture</title><link href="/fixture.epub" rel="http://opds-spec.org/acquisition" /></entry></feed>'
    row = parse_opds(raw, "https://www.textos.info/new.atom")[0]
    assert row["review_status"] == "pending" and row["license"] is None
    assert row["declarations"]["links"][0]["url"] == "https://www.textos.info/fixture.epub"
    with pytest.raises(ValueError, match="DTD"):
        parse_opds(b'<!DOCTYPE x><feed/>', "https://www.textos.info")
    row = parse_openlibrary(json.dumps({"docs": [{"key": "/works/fixture", "ebook_access": "borrowable"}]}))[0]
    assert row["declarations"]["ebook_access"] == "borrowable" and row["training_allowed"] is False


def test_robots_block_recorded_and_no_metadata_requested(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"format": "hyd-book-source-catalog/1", "sources": [
        {"id": "openlibrary", "metadata_url": "https://openlibrary.org/search.json?q=fixture"}]}))
    opener = Opener([b"User-agent: *\nDisallow: /search.json\n"])
    result = discover(catalog, "openlibrary", tmp_path / "out", opener=opener)
    assert result["state"] == "blocked-by-robots" and len(opener.calls) == 1
    assert (tmp_path / "out/robots.txt").exists() and not (tmp_path / "out/metadata.raw").exists()
