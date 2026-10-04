import io
import json

import pytest

from hyd_calibrator.downloader import download_asset, validate_plan


def plan(**changes):
    return {"format": "hyd-corpus-download-plan/1", "source_id": "boe", "asset_url": "https://www.boe.es/fixture.xml",
            "max_bytes": 1024, "rights": {"verified": True, "license": "public-domain", "evidence_url": "https://www.boe.es/review"},
            "training_allowed": False, "state": "prepared", **changes}


class FakeOpener:
    def __init__(self, body):
        self.body = body

    def open(self, request, timeout):
        response = io.BytesIO(self.body)
        response.status = 200
        response.headers = {"Content-Length": str(len(self.body))}
        return response


def test_download_hash_and_no_training_permission(tmp_path):
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan()), encoding="utf-8")
    report = download_asset(source, tmp_path / "download", opener=FakeOpener(b"fixture bytes"))
    assert report["bytes"] == 13 and report["training_allowed"] is False
    assert (tmp_path / "download/asset.raw").read_bytes() == b"fixture bytes"
    assert report["rights_basis"] == "user-reviewed-declaration"


@pytest.mark.parametrize("change", [
    {"source_id": "elpais"}, {"asset_url": "https://www.boe.es.evil.example/file"},
    {"asset_url": "http://www.boe.es/file"}, {"asset_url": "https://user:password@www.boe.es/file"},
    {"asset_url": "https://127.0.0.1/file"}, {"max_bytes": True}, {"training_allowed": True},
    {"rights": {"verified": False, "license": "public-domain", "evidence_url": "https://www.boe.es/review"}},
])
def test_unreviewed_and_unsafe_plans_rejected(change):
    with pytest.raises(ValueError):
        validate_plan(plan(**change))


def test_byte_budget_fails_without_completed_asset(tmp_path):
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan()), encoding="utf-8")
    with pytest.raises(ValueError, match="budget"):
        download_asset(source, tmp_path / "download", opener=FakeOpener(b"x" * 2048))
    assert not (tmp_path / "download/manifest.json").exists()
    assert not (tmp_path / "download/asset.raw").exists()
    assert json.loads((tmp_path / "download/failed.json").read_text())["state"] == "failed"


def test_cancellation_during_transfer_keeps_partial_unapproved(tmp_path):
    from hyd_calibrator.downloader import DownloadCancelled
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan()), encoding="utf-8")
    checks = []
    def cancelled():
        checks.append(True)
        return len(checks) >= 3
    with pytest.raises(DownloadCancelled):
        download_asset(source, tmp_path / "download", opener=FakeOpener(b"fixture"), cancel_check=cancelled)
    assert (tmp_path / "download/asset.part").exists()
    assert not (tmp_path / "download/asset.raw").exists()
    assert not (tmp_path / "download/manifest.json").exists()
