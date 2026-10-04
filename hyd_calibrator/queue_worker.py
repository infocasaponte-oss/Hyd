# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Consume the app's authenticated filesystem queue without running shell commands."""
import json
import hashlib
import re
from pathlib import Path

from .atomic import write_text_atomic
from .downloader import download_asset, DownloadCancelled


def run_queue(root, *, max_jobs=10, opener=None):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("configured queue directory does not exist")
    if type(max_jobs) is not int or not 1 <= max_jobs <= 20:
        raise ValueError("max_jobs must be between 1 and 20")
    results = []
    for actor in sorted(root.iterdir()):
        if actor.is_symlink() or not actor.is_dir() or not re.fullmatch(r"[0-9a-f]{64}", actor.name):
            continue
        for folder in sorted(actor.iterdir()):
            if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r"[0-9a-f-]{36}", folder.name):
                continue
            if (folder / "result.json").exists() or not (folder / "queued").is_file():
                continue
            try:
                (folder / "queued").rename(folder / "running")
            except FileNotFoundError:
                continue  # another worker claimed this job
            try:
                request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
                if request.get("id") != folder.name or request.get("actor_key") != actor.name:
                    raise ValueError("queue ownership metadata mismatch")
                if hashlib.sha256((folder / "plan.json").read_bytes()).hexdigest() != request.get("plan_sha256"):
                    raise ValueError("queued plan changed after submission")
                result = download_asset(folder / "plan.json", folder / "download", opener=opener,
                                        cancel_check=lambda: (folder / "cancel").exists())
            except DownloadCancelled:
                result = {"state": "cancelled", "training_allowed": False}
            except Exception as error:
                # No raw exception strings (URLs/tokens) are exported to the app.
                result = {"state": "failed", "error_type": type(error).__name__, "training_allowed": False}
            write_text_atomic(folder / "result.json", json.dumps(result, indent=2, allow_nan=False))
            results.append({"id": folder.name, "state": result["state"]})
            if len(results) >= max_jobs:
                return results
    return results
