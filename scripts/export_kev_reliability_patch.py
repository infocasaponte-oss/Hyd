# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Keep the ignored experimental Kev changes reproducible inside HYDRA."""
import hashlib
import json
import subprocess
from pathlib import Path


if __name__ == "__main__":
    source = Path("runtime/kev-hydra")
    output = Path("patches/kev")
    output.mkdir(parents=True, exist_ok=True)
    patch = subprocess.check_output(["git", "-C", str(source), "diff", "--no-ext-diff", "--binary", "HEAD"], stderr=subprocess.DEVNULL)
    (output / "hydra-reliability-v1.patch").write_bytes(patch)
    names = subprocess.check_output(["git", "-C", str(source), "diff", "--name-only", "HEAD"], text=True, stderr=subprocess.DEVNULL).splitlines()
    manifest = {"upstream": "https://github.com/jaredpalmer/kev", "license": "Apache-2.0",
                "base_revision": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
                "patch_sha256": hashlib.sha256(patch).hexdigest(),
                "files": {name: hashlib.sha256((source / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in names},
                "scope": "HYDRA local reliability fork, no upstream publication or model promotion"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"files": len(names), "patch_sha256": manifest["patch_sha256"]}))
