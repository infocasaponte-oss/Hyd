import hashlib
import io
import json

from hyd_calibrator.queue_worker import run_queue


def job(root, *, cancelled=False):
    actor = "a" * 64
    job_id = "00000000-0000-4000-8000-000000000001"
    folder = root / actor / job_id
    folder.mkdir(parents=True)
    plan = {"format": "hyd-corpus-download-plan/1", "source_id": "boe", "asset_url": "https://www.boe.es/fixture.xml",
            "max_bytes": 1024, "rights": {"verified": True, "license": "public-domain", "evidence_url": "https://www.boe.es/review"},
            "training_allowed": False, "state": "prepared"}
    raw = json.dumps(plan)
    (folder / "plan.json").write_text(raw, encoding="utf-8")
    (folder / "request.json").write_text(json.dumps({"id": job_id, "actor_key": actor,
        "plan_sha256": hashlib.sha256(raw.encode()).hexdigest()}), encoding="utf-8")
    (folder / "queued").touch()
    if cancelled:
        (folder / "cancel").touch()
    return folder


class FakeOpener:
    def __init__(self):
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        response = io.BytesIO(b"fixture")
        response.status = 200
        response.headers = {"Content-Length": "7"}
        return response


def test_worker_claims_once_and_persists_real_result(tmp_path):
    folder = job(tmp_path)
    opener = FakeOpener()
    result = run_queue(tmp_path, opener=opener)
    assert result[0]["state"] == "downloaded" and opener.calls == 1
    assert run_queue(tmp_path, opener=opener) == []
    persisted = json.loads((folder / "result.json").read_text())
    assert persisted["bytes"] == 7 and persisted["training_allowed"] is False
    assert (folder / "download/asset.raw").read_bytes() == b"fixture"


def test_cancelled_queue_never_opens_network(tmp_path):
    folder = job(tmp_path, cancelled=True)
    opener = FakeOpener()
    assert run_queue(tmp_path, opener=opener)[0]["state"] == "cancelled"
    assert opener.calls == 0
    assert not (folder / "download").exists()


def test_changed_queued_plan_fails_without_network(tmp_path):
    folder = job(tmp_path)
    with (folder / "plan.json").open("a") as handle:
        handle.write(" ")
    opener = FakeOpener()
    assert run_queue(tmp_path, opener=opener)[0]["state"] == "failed"
    assert opener.calls == 0
