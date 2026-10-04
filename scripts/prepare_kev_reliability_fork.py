# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Recreate the reviewed Kev fork from its pinned checkout and tracked patch."""
import hashlib
import json
import subprocess
from pathlib import Path


def validate(source, manifest):
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != manifest["base_revision"]:
        raise ValueError("Kev fork base revision changed")
    for name, expected in manifest["files"].items():
        target = (source / name).resolve()
        target.relative_to(source.resolve())
        actual = hashlib.sha256(target.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            raise ValueError(f"Kev fork differs from the reviewed patch: {name}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    source = root / "runtime/kev-hydra"
    directory = root / "patches/kev"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    patch = directory / "hydra-reliability-v1.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["patch_sha256"]:
        raise ValueError("Tracked patch hash changed")
    if not source.exists():
        original = root / "runtime/kev"
        subprocess.run(["git", "-C", str(original), "worktree", "add", "--detach", str(source), manifest["base_revision"]], check=True)
        subprocess.run(["git", "-C", str(source), "apply", "--check", str(patch)], check=True)
        subprocess.run(["git", "-C", str(source), "apply", str(patch)], check=True)
    validate(source, manifest)
    print(json.dumps({"status": "VERIFIED", "source": str(source), "base_revision": manifest["base_revision"]}))
