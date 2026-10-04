# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Download a deterministic slice of PleIAs Spanish public-domain books and newspapers.

Both collections declare public domain in all regions (authors dead > 70 years, EU Copyright
Directive art. 14), so they pass ``base_data_policy`` as "public-domain". Files land in
``data/sources/pleias/<collection>/`` with a manifest of sha256 per file. The dataset revision
(commit sha) is resolved once and pinned in the manifest, so listing and downloads always use the
same immutable state and a resumed run cannot mix revisions. Interrupted downloads are retried.
Repository names too long for a Windows path component are stored under a short local name
(``local`` in the manifest entry); the manifest keys stay the repository names.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

from huggingface_hub import HfApi, get_session, hf_hub_download, hf_hub_url
from huggingface_hub.utils import build_hf_headers

COLLECTIONS = {"spanish-pd-books": "PleIAs/Spanish-PD-Books", "spanish-pd-newspapers": "PleIAs/Spanish-PD-Newspapers"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


MAX_NAME = 120  # leaves room for huggingface_hub's ".<sha256>.incomplete" suffix within 255 characters


def local_name(name: str) -> str:
    """The repository name, or a short stable one when it would not fit a Windows path component."""
    if len(name) <= MAX_NAME:
        return name
    stem = name[:-len(".parquet")] if name.endswith(".parquet") else name
    return f"{stem[:60]}-{hashlib.sha256(name.encode()).hexdigest()[:16]}.parquet"


def _stream(repo: str, name: str, revision: str, path: Path) -> Path:
    url = hf_hub_url(repo, name, repo_type="dataset", revision=revision)
    partial = path.with_name(path.name + ".part")
    with get_session().get(url, headers=build_hf_headers(), stream=True, timeout=60) as response:
        response.raise_for_status()
        with partial.open("wb") as stream:
            for block in response.iter_content(8 << 20):
                stream.write(block)
    partial.replace(path)
    return path


def download(repo: str, name: str, revision: str, target: Path, attempts: int = 6) -> Path:
    for attempt in range(1, attempts + 1):
        try:
            if local_name(name) != name:
                return _stream(repo, name, revision, target / local_name(name))
            return Path(hf_hub_download(repo, name, repo_type="dataset", revision=revision, local_dir=target))
        except Exception as exc:  # broken connections are common on multi-hundred-MB files
            if attempt == attempts:
                raise
            print(f"retry {attempt}/{attempts - 1} for {name}: {type(exc).__name__}", flush=True)
            time.sleep(min(300, 15 * 2 ** attempt))
    raise AssertionError("unreachable")


def fetch(collection: str, count: int, root: Path) -> dict:
    repo = COLLECTIONS[collection]
    target = root / collection
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "repo": repo, "license": "public-domain", "files": {}}
    api = HfApi()
    # Pin the revision on first use; files fetched before pinning are re-verified against it.
    revision = manifest.get("revision") or api.dataset_info(repo).sha
    if "revision" not in manifest:
        manifest["revision"] = revision
    files = sorted(f for f in api.list_repo_files(repo, repo_type="dataset", revision=revision)
                   if f.endswith(".parquet"))[:count]
    manifest["selection"] = {"rule": "sorted parquet prefix", "count": count}
    for name in files:
        if name in manifest["files"] and (target / local_name(name)).exists():
            continue
        local = download(repo, name, revision, target)
        manifest["files"][name] = {"bytes": local.stat().st_size, "sha256": sha256(local)}
        if local.name != name:
            manifest["files"][name]["local"] = local.name
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"{collection}: {name} ({local.stat().st_size / 1e6:.0f} MB)", flush=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"collection": collection, "revision": revision, "files": len(manifest["files"]),
            "gb": round(sum(f["bytes"] for f in manifest["files"].values()) / 1e9, 2)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", type=int, default=12)
    parser.add_argument("--newspapers", type=int, default=50)
    parser.add_argument("--root", type=Path, default=Path("data/sources/pleias"))
    args = parser.parse_args()
    print(json.dumps([fetch("spanish-pd-books", args.books, args.root),
                      fetch("spanish-pd-newspapers", args.newspapers, args.root)]))
