"""Export committed source trees without local credentials or cloud dependencies."""
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, encoding="utf-8").strip()


def export(hyd, app, out):
    out = Path(out)
    if out.exists():
        raise ValueError("choose a new export directory")
    repos = {"hyd": Path(hyd).resolve(strict=True), "calibrator-app": Path(app).resolve(strict=True)}
    for repo in repos.values():
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            raise ValueError("commit source changes before exporting")
        files = git(repo, "ls-files").splitlines()
        if any(Path(f).name == ".env" or Path(f).name.startswith(".env.") and Path(f).name != ".env.example"
               for f in files):
            raise ValueError("tracked environment credentials must not be exported")
    out.mkdir(parents=True)
    result = {"format": "hyd-factory-source-bundle/1", "complete": False, "artifacts": {},
              "includes_weights": False, "includes_corpus": False, "production_ready": False}
    for name, repo in repos.items():
        revision = git(repo, "rev-parse", "HEAD")
        target = out / f"{name}-source.zip"
        subprocess.run(["git", "-C", str(repo), "archive", "--format=zip", f"--output={target.resolve()}", revision],
                       check=True)
        h = hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        result["artifacts"][name] = {"file": target.name, "git_revision": revision,
                                      "bytes": target.stat().st_size, "sha256": h.hexdigest()}
    result["complete"] = True
    (out / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hyd", required=True, type=Path)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.hyd, args.app, args.out), indent=2))
