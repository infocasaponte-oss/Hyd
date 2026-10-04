# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Artifact Store: manifests on the event log (files or PostgreSQL ``hydra_logs``), blobs on a directory
or an S3-compatible bucket.

PostgreSQL cases need HYDRA_IT_POSTGRES (``pg_url`` in conftest). The real-bucket case needs
HYDRA_IT_S3 (an endpoint such as MinIO) plus AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, e.g.
    docker run -d -p 127.0.0.1:19000:9000 minio/minio server /data
    HYDRA_IT_S3=http://127.0.0.1:19000 AWS_ACCESS_KEY_ID=minioadmin AWS_SECRET_ACCESS_KEY=minioadmin
"""
from __future__ import annotations

import io
import os
import uuid

import pytest

from hydra.artifacts.blobs import LocalBlobs, S3Blobs, open_blobs
from hydra.artifacts.store import ArtifactStore
from hydra.core.eventlog import LogSpace
from hydra.core.hashing import sha256_hex
from hydra.governance.recovery import backup, restore


class FakeS3:
    """The subset of the boto3 S3 client the store uses, with botocore-shaped errors."""

    class ClientError(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts = 0

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.ClientError("404")
        return {}

    def put_object(self, Bucket, Key, Body):
        self.puts += 1
        self.objects[(Bucket, Key)] = bytes(Body)

    def upload_file(self, Filename, Bucket, Key):
        with open(Filename, "rb") as f:
            self.put_object(Bucket, Key, f.read())

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.ClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


@pytest.fixture(params=["local", "s3"])
def blobs(request, tmp_path):
    if request.param == "local":
        return LocalBlobs(tmp_path / "objects")
    return S3Blobs("s3://bucket/hydra/", client=FakeS3())


def test_blob_contract(blobs, tmp_path):
    raw = b"hello artifacts"
    digest = sha256_hex(raw)
    assert not blobs.exists(digest) and blobs.digest_of(digest) is None
    blobs.put(digest, raw)
    blobs.put(digest, raw)  # idempotent
    assert blobs.exists(digest) and blobs.get(digest) == raw and blobs.digest_of(digest) == digest
    src = tmp_path / "f.bin"
    src.write_bytes(b"\x00" * 3_000_000)
    big = sha256_hex(src.read_bytes())
    blobs.put_file(big, src)
    assert blobs.digest_of(big) == big
    blobs.overwrite(digest, b"tampered")
    assert blobs.digest_of(digest) != digest
    blobs.delete(digest)
    assert blobs.digest_of(digest) is None
    with pytest.raises(FileNotFoundError):
        blobs.get(digest)


def test_s3_keys_and_write_once():
    s3 = FakeS3()
    b = S3Blobs("s3://bucket/a/b", client=s3)
    assert b.key("ab" + "c" * 62) == "a/b/sha256/ab/cc/ab" + "c" * 62
    assert S3Blobs("s3://bucket", client=s3).key("0" * 64).startswith("sha256/00/00/")
    b.put("0" * 64, b"x")
    b.put("0" * 64, b"x")
    assert s3.puts == 1
    with pytest.raises(ValueError):
        S3Blobs("https://bucket", client=s3)


def test_open_blobs(tmp_path):
    assert open_blobs("", tmp_path / "d").root == tmp_path / "d"
    assert open_blobs(str(tmp_path / "shared"), tmp_path / "d").root == tmp_path / "shared"


@pytest.fixture(params=["file", "postgres"])
def space(request):
    if request.param == "file":
        yield LogSpace(label="artifacts")
        return
    s = LogSpace(request.getfixturevalue("pg_url"), label="artifacts")
    yield s
    s.close()


def test_store_contract(space, blobs, tmp_path):
    store = ArtifactStore(tmp_path / "artifacts", logs=space, blobs=blobs)
    a = store.put("patch v1", task_id="t1")
    b = store.put_json({"k": 1}, parents=[a.artifact_id], task_id="t1")
    src = tmp_path / "report.txt"
    src.write_text("report", encoding="utf-8")
    c = store.put_file(src, task_id="t2")
    assert store.text(a.uri) == "patch v1" and store.get(c.artifact_id) == b"report"
    again = ArtifactStore(tmp_path / "artifacts", logs=space, blobs=blobs)
    assert [m.artifact_id for m in again.lineage(b.artifact_id)] == [b.artifact_id, a.artifact_id]
    assert {m.artifact_id for m in again.for_task("t1")} == {a.artifact_id, b.artifact_id}
    assert again.verify() == {"ok": True, "objects": 3, "corrupt_or_missing": []}
    blobs.overwrite(a.sha256, b"tampered")
    assert again.verify()["corrupt_or_missing"] == [a.sha256]


def test_two_nodes_share_artifacts(pg_url, tmp_path):
    blobs = S3Blobs("s3://shared", client=FakeS3())
    a = ArtifactStore(tmp_path / "a", logs=LogSpace(pg_url, label="artifacts"), blobs=blobs, refresh_s=0)
    b = ArtifactStore(tmp_path / "b", logs=LogSpace(pg_url, label="artifacts"), blobs=blobs, refresh_s=0)
    m = a.put("made on node a", task_id="t")
    assert b.text(m.artifact_id) == "made on node a"
    assert b.stats() == a.stats() == {"manifests": 1, "objects": 1, "bytes": len("made on node a")}


def test_backup_exports_postgres_manifests_and_restore_verifies_shared_blobs(pg_url, tmp_path):
    space = LogSpace(pg_url, label="artifacts")
    blobs = S3Blobs("s3://shared", client=FakeS3())
    data = tmp_path / "data"
    store = ArtifactStore(data / "artifacts", logs=space, blobs=blobs)
    store.put("in the bucket")
    manifest = backup(data, tmp_path / "b.tar.gz", logs=[space])
    assert "artifacts/manifests.jsonl" in manifest.files
    report = restore(tmp_path / "b.tar.gz", tmp_path / "restored", blobs=blobs)
    assert report.ok and report.artifacts["objects"] == 1
    # verified against local objects/ instead, the bucket's blob is reported missing
    assert not restore(tmp_path / "b.tar.gz", tmp_path / "again").ok
    space.close()


@pytest.mark.skipif(not os.environ.get("HYDRA_IT_S3"), reason="set HYDRA_IT_S3 to an S3-compatible endpoint")
def test_real_bucket(tmp_path):
    boto3 = pytest.importorskip("boto3")
    endpoint = os.environ["HYDRA_IT_S3"]
    bucket = f"hydra-it-{uuid.uuid4().hex[:10]}"
    s3 = boto3.client("s3", endpoint_url=endpoint)
    s3.create_bucket(Bucket=bucket)
    try:
        blobs = open_blobs(f"s3://{bucket}/cas", tmp_path / "unused", endpoint)
        assert isinstance(blobs, S3Blobs)
        store = ArtifactStore(tmp_path / "artifacts", blobs=blobs)
        m = store.put("real bucket")
        assert store.text(m.uri) == "real bucket" and store.verify()["ok"]
        blobs.overwrite(m.sha256, b"x")
        assert not store.verify()["ok"]
    finally:  # leave the server as it was
        for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=bucket)


def test_switching_to_s3_migrates_existing_objects_once(tmp_path, monkeypatch):
    local_root = tmp_path / "artifacts" / "objects"
    before = ArtifactStore(tmp_path / "artifacts")
    a = before.put("written before the switch")
    b = before.put("this one gets corrupted")
    LocalBlobs(local_root).overwrite(b.sha256, b"bit rot")
    s3 = FakeS3()
    real_init = S3Blobs.__init__
    monkeypatch.setattr(S3Blobs, "__init__", lambda self, url, endpoint_url="": real_init(self, url, client=s3))
    blobs = open_blobs("s3://bucket/cas", local_root)
    after = ArtifactStore(tmp_path / "artifacts", blobs=blobs)
    assert after.text(a.artifact_id) == "written before the switch"
    assert after.verify()["corrupt_or_missing"] == [b.sha256]  # corrupt objects are not copied
    assert not (local_root / ".migrated-to").exists()  # incomplete: retried on the next start
    LocalBlobs(local_root).overwrite(b.sha256, b"this one gets corrupted")
    puts = s3.puts
    open_blobs("s3://bucket/cas", local_root)
    assert s3.puts == puts + 1 and (local_root / ".migrated-to").read_text() == "s3://bucket/cas/"
    open_blobs("s3://bucket/cas", local_root)
    assert s3.puts == puts + 1  # migrated once
    assert (local_root / a.sha256[:2] / a.sha256[2:4] / a.sha256).exists()  # local copies kept


def test_backups_leave_out_credential_files(tmp_path):
    data = tmp_path / "data"
    (data / "secrets").mkdir(parents=True)
    (data / "secrets" / "minio.env").write_text("MINIO_ROOT_PASSWORD=x", encoding="utf-8")
    (data / ".env").write_text("A=1", encoding="utf-8")
    (data / "notes.txt").write_text("kept", encoding="utf-8")
    assert set(backup(data, tmp_path / "b.tar.gz").files) == {"notes.txt"}
    assert {"secrets/minio.env", ".env", "notes.txt"} <= set(
        backup(data, tmp_path / "c.tar.gz", include_private_keys=True).files)
