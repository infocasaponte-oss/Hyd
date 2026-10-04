# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Read-only reproducible source inventory. Never imports the audited project."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


def audit(root: Path) -> dict:
    files, errors = [], []
    ignored = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    text_extensions = {".py", ".json", ".jsonl", ".md", ".toml", ".yaml", ".yml",
                       ".ts", ".tsx", ".js", ".mjs", ".html", ".css", ".sh", ".ps1"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ignored.intersection(path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
            entry = {"path": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            if path.suffix in text_extensions or path.name in {"LICENSE", ".gitignore", ".gitattributes"}:
                source = raw.decode("utf-8-sig")
                entry["lines"] = len(source.splitlines())
                # Record connection identifiers, never credential values or user records.
                if path.suffix in {".py", ".ts", ".tsx", ".js", ".mjs", ".toml", ".yaml", ".yml", ".sh", ".ps1"}:
                    entry["external_hosts"] = sorted(set(re.findall(r"https?://([A-Za-z0-9.-]+)", source)))
                    entry["environment_names"] = sorted(set(re.findall(r"\b(?:KEV|HF|MODAL|AI_GATEWAY|VERCEL)_[A-Z0-9_]+\b", source)))
                if path.suffix == ".py":
                    tree = ast.parse(source, filename=rel)
                    entry["imports"] = sorted(set(
                        n.module or "" if isinstance(n, ast.ImportFrom) else a.name
                        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                        for a in (n.names if isinstance(n, ast.Import) else [None])))
                    entry["symbols"] = [{"name": n.name, "line": n.lineno,
                        "end_line": n.end_lineno, "kind": type(n).__name__,
                        "docstring": ast.get_docstring(n),
                        "signature": ast.unparse(n.args) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else None,
                        "calls": sorted(set(ast.unparse(c.func) for c in ast.walk(n) if isinstance(c, ast.Call)))}
                        for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                    risky = {"eval", "exec", "run", "Popen", "system", "load", "from_pretrained", "snapshot_download"}
                    entry["review_calls"] = [{"line": n.lineno, "call": ast.unparse(n.func)}
                        for n in ast.walk(tree) if isinstance(n, ast.Call) and
                        (n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else "") in risky]
            files.append(entry)
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append({"path": rel, "error": str(exc)})
    return {"format": "hyd-source-audit/1", "root": str(root.resolve()),
            "method": "Full file hashing; UTF-8 text reads; Python AST symbols/imports/call sites. Static evidence only.",
            "excluded_directory_names": sorted(ignored), "files": files, "errors": errors,
            "summary": {"files": len(files), "bytes": sum(f["bytes"] for f in files),
                        "python_files": sum(f["path"].endswith(".py") for f in files),
                        "symbols": sum(len(f.get("symbols", [])) for f in files),
                        "extensions": dict(Counter(Path(f["path"]).suffix for f in files))}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "errors": report["errors"]}))
