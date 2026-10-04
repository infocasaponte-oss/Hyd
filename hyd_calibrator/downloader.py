# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Bounded raw-asset downloader for reviewed plans exported by the Corpus tab."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .atomic import write_text_atomic
from .work_rights import BOOK_HOSTS, validate_work, verify_work_files

HOSTS = {"boe": {"www.boe.es", "boe.es"}, "congreso": {"www.congreso.es", "congreso.es"},
         "rtve": {"www.rtve.es", "rtve.es"}, "gutenberg": {"www.gutenberg.org", "gutenberg.org"},
         "cervantes": {"www.cervantesvirtual.com", "cervantesvirtual.com"}}
LICENSES = {"CC0-1.0", "CC-BY-4.0", "public-domain", "eu-reuse-2011-833"}


class DownloadCancelled(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect not permitted; review and export the final asset URL")


def validate_plan(plan):
    fields = {"format", "source_id", "asset_url", "max_bytes", "rights", "training_allowed", "state"}
    version = plan.get("format") if isinstance(plan, dict) else None
    if version == "hyd-corpus-download-plan/2":
        fields.add("work_review")
    if not isinstance(plan, dict) or set(plan) != fields:
        raise ValueError("invalid download plan structure")
    if version not in ("hyd-corpus-download-plan/1", "hyd-corpus-download-plan/2") or plan["state"] != "prepared" or plan["training_allowed"] is not False:
        raise ValueError("prepared unapproved-training plan required")
    source = plan["source_id"]
    hosts = {**HOSTS, **BOOK_HOSTS}
    if not isinstance(source, str) or source not in hosts:
        raise ValueError("source not enabled in local downloader policy")
    if source in BOOK_HOSTS and version != "hyd-corpus-download-plan/2":
        raise ValueError("books require per-work review in download plan/2")
    if not isinstance(plan["asset_url"], str):
        raise ValueError("invalid asset URL")
    url = urlsplit(plan["asset_url"])
    if (url.scheme != "https" or url.hostname not in hosts[source] or url.username or url.password
            or url.port not in (None, 443) or url.fragment):
        raise ValueError("HTTPS asset on the source's exact official host required")
    if type(plan["max_bytes"]) is not int or not 1024 <= plan["max_bytes"] <= 1024 ** 3:
        raise ValueError("explicit download budget required (1 KiB to 1 GiB)")
    rights = plan["rights"]
    if not isinstance(rights, dict) or set(rights) != {"verified", "license", "evidence_url"}:
        raise ValueError("explicit rights review required")
    if rights["verified"] is not True or not isinstance(rights.get("license"), str) or rights["license"] not in LICENSES:
        raise ValueError("reviewed rights declaration and admitted licence label required")
    if (not isinstance(rights["evidence_url"], str) or urlsplit(rights["evidence_url"]).scheme != "https"
            or not urlsplit(rights["evidence_url"]).hostname):
        raise ValueError("HTTPS evidence URL required")
    if version == "hyd-corpus-download-plan/2":
        if source not in BOOK_HOSTS:
            raise ValueError("book plan requires a supported book source")
        validate_work(plan["work_review"], source, plan["asset_url"], rights["license"])
    return plan


def download_asset(plan_path, out, *, opener=None, cancel_check=None):
    plan_path, out = Path(plan_path), Path(out)
    if out.exists():
        raise ValueError("download output already exists")
    raw = plan_path.read_bytes()
    plan = validate_plan(json.loads(raw))
    if plan["format"] == "hyd-corpus-download-plan/2":
        verify_work_files(plan["work_review"], plan_path.parent)
    if cancel_check and cancel_check():
        raise DownloadCancelled("download cancelled before network access")
    opener = opener or build_opener(NoRedirect())
    request = Request(plan["asset_url"], headers={"User-Agent": "HYDRA-Corpus-Review/1", "Accept-Encoding": "identity"})
    out.mkdir(parents=True, exist_ok=False)
    count, digest = 0, hashlib.sha256()
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise ValueError("download requires a successful full response")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > plan["max_bytes"]:
                raise ValueError("asset exceeds declared byte budget")
            with (out / "asset.part").open("xb") as handle:
                while True:
                    if cancel_check and cancel_check():
                        raise DownloadCancelled("download cancellation requested")
                    chunk = response.read(min(1024 * 1024, plan["max_bytes"] - count + 1))
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > plan["max_bytes"]:
                        raise ValueError("download exceeded declared byte budget")
                    handle.write(chunk)
                    digest.update(chunk)
            if length is not None and count != int(length):
                raise ValueError("incomplete asset response")
            if count == 0:
                raise ValueError("empty asset response")
        (out / "asset.part").rename(out / "asset.raw")
        report = {"format": "hyd-corpus-download-result/1", "state": "downloaded", "bytes": count,
                  "sha256": digest.hexdigest(), "plan_sha256": hashlib.sha256(raw).hexdigest(),
                  "source_id": plan["source_id"], "asset_url": plan["asset_url"], "rights": plan["rights"],
                  "rights_basis": "user-reviewed-declaration", "training_allowed": False}
        if plan["format"] == "hyd-corpus-download-plan/2":
            report["work_review"] = plan["work_review"]
            report["rights_basis"] = "human-per-work-declaration-with-verified-evidence-files"
        write_text_atomic(out / "manifest.json", json.dumps(report, indent=2))
        return report
    except Exception:
        write_text_atomic(out / "failed.json", json.dumps({"state": "failed", "bytes_received": count,
                                                          "training_allowed": False}))
        raise
