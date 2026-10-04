# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Blob storage for the content-addressed Artifact Store: a local directory or an S3-compatible bucket.

Objects are immutable and named by their sha256 (``sha256/ab/cd/abcdef...`` in a bucket,
``objects/ab/cd/abcdef...`` on disk), so every node may write the same object and readers verify it
by re-hashing. ``HYDRA_ARTIFACT_OBJECTS``: empty (``<data>/artifacts/objects``) or
``s3://bucket/prefix``; ``HYDRA_S3_ENDPOINT_URL`` points at MinIO/Ceph/R2, credentials come from the
standard AWS variables. S3 requires ``boto3`` (``pip install "hydra-engine[s3]"``)."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

log = logging.getLogger("hydra.artifacts")

_CHUNK = 1 << 20


class LocalBlobs:
    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest[2:4] / digest

    @property
    def location(self) -> str:
        return str(self.root.resolve())

    def digests(self):
        """Digests of the objects stored here (files named by their sha256)."""
        for p in sorted(self.root.glob("??/??/*")):
            if p.is_file() and len(p.name) == 64 and p.parent.parent.name == p.name[:2]:
                yield p.name

    def exists(self, digest: str) -> bool:
        return self.path(digest).exists()

    def put(self, digest: str, raw: bytes) -> None:
        path = self.path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(raw)
            tmp.replace(path)

    def put_file(self, digest: str, src: Path) -> None:
        path = self.path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            shutil.copyfile(src, tmp)
            tmp.replace(path)

    def get(self, digest: str) -> bytes:
        return self.path(digest).read_bytes()

    def digest_of(self, digest: str) -> str | None:
        """sha256 of what is stored under ``digest`` (None when missing): verification re-hashes."""
        path = self.path(digest)
        if not path.exists():
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
        return h.hexdigest()

    def overwrite(self, digest: str, raw: bytes) -> None:
        """Replace an object bypassing content addressing (red-team corruption probes only)."""
        path = self.path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def delete(self, digest: str) -> None:
        self.path(digest).unlink(missing_ok=True)


class S3Blobs:
    backend = "s3"

    def __init__(self, url: str, endpoint_url: str = "", client=None) -> None:
        if not url.startswith("s3://"):
            raise ValueError(f"not an s3:// URL: {url!r}")
        bucket, _, prefix = url[5:].partition("/")
        if not bucket:
            raise ValueError(f"no bucket in {url!r}")
        self.bucket = bucket
        self.prefix = (prefix.strip("/") + "/") if prefix.strip("/") else ""
        if client is None:
            import boto3  # optional dependency

            client = boto3.client("s3", endpoint_url=endpoint_url or None)
        self._s3 = client

    def key(self, digest: str) -> str:
        return f"{self.prefix}sha256/{digest[:2]}/{digest[2:4]}/{digest}"

    def _missing(self, error) -> bool:
        code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
        return code in ("404", "NoSuchKey", "NotFound")

    def exists(self, digest: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self.key(digest))
            return True
        except Exception as e:  # botocore.exceptions.ClientError
            if self._missing(e):
                return False
            raise

    def put(self, digest: str, raw: bytes) -> None:
        if not self.exists(digest):
            self._s3.put_object(Bucket=self.bucket, Key=self.key(digest), Body=raw)

    def put_file(self, digest: str, src: Path) -> None:
        if not self.exists(digest):
            self._s3.upload_file(str(src), self.bucket, self.key(digest))

    @property
    def location(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    def get(self, digest: str) -> bytes:
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=self.key(digest))["Body"].read()
        except Exception as e:
            if self._missing(e):
                raise FileNotFoundError(f"{self.bucket}/{self.key(digest)}") from None
            raise

    def digest_of(self, digest: str) -> str | None:
        try:
            body = self._s3.get_object(Bucket=self.bucket, Key=self.key(digest))["Body"]
        except Exception as e:
            if self._missing(e):
                return None
            raise
        h = hashlib.sha256()
        for chunk in iter(lambda: body.read(_CHUNK), b""):
            h.update(chunk)
        return h.hexdigest()

    def overwrite(self, digest: str, raw: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=self.key(digest), Body=raw)

    def delete(self, digest: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self.key(digest))


MIGRATION_MARKER = ".migrated-to"


def migrate_blobs(source: LocalBlobs, target: LocalBlobs | S3Blobs) -> dict[str, int]:
    """Copy the objects of a local store into ``target`` once, so manifests written before the switch
    keep resolving. Each object is re-hashed first: a corrupt one is reported and not copied. The
    source is kept untouched; a marker records the completed migration (it is redone, cheaply, when
    the target changes or a previous run did not finish)."""
    marker = source.root / MIGRATION_MARKER
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == target.location:
        return {"copied": 0, "present": 0, "corrupt": 0}
    counts = {"copied": 0, "present": 0, "corrupt": 0}
    for digest in source.digests():
        if target.exists(digest):
            counts["present"] += 1
        elif source.digest_of(digest) != digest:
            counts["corrupt"] += 1
            log.error("artifact object %s does not match its hash: not copied to %s", digest, target.location)
        else:
            target.put_file(digest, source.path(digest))
            counts["copied"] += 1
    if not counts["corrupt"]:
        marker.write_text(target.location, encoding="utf-8")
    if counts["copied"] or counts["corrupt"]:
        log.warning("artifact objects migrated from %s to %s: %s (the local copies are kept)",
                    source.location, target.location, counts)
    return counts


def open_blobs(objects: str, default_root: Path, endpoint_url: str = "") -> LocalBlobs | S3Blobs:
    """``objects``: empty (``default_root``), a directory, or ``s3://bucket/prefix``. When it is not
    ``default_root``, the objects already stored there are migrated once (``migrate_blobs``)."""
    if objects.startswith("s3://"):
        try:
            target: LocalBlobs | S3Blobs = S3Blobs(objects, endpoint_url)
        except ImportError:
            raise RuntimeError('S3 artifact storage needs boto3: pip install "hydra-engine[s3]"') from None
    else:
        target = LocalBlobs(Path(objects) if objects else default_root)
    if Path(default_root).is_dir() and target.location != str(Path(default_root).resolve()):
        migrate_blobs(LocalBlobs(default_root), target)
    return target
