# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Public surface of HYDRA (engine and model factory), pinned while the platform and runtime lines are
unified (docs/PLAN_UNIFICACION_LINEAS_2026-10-01.md, F0).

* ``http.json``: every gateway operation (method, path, parameters, request and response schemas,
  including the runtime routes mounted into the gateway) and the schemas they reference;
* ``cli.json``: the whole ``hydra`` command tree with its options;
* ``cross_imports.json``: what the platform imports from ``hydra.runtime`` (may only shrink).

Descriptions, titles and examples are ignored: documentation may change, the contract may not.
After an intended change, regenerate and commit the diff:

    python -m tests.contracts.surface --update
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
_DOC_KEYS = {"title", "description", "summary", "example", "examples", "x-logo"}


def _strip_docs(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_docs(v) for k, v in sorted(node.items()) if k not in _DOC_KEYS}
    if isinstance(node, list):
        return [_strip_docs(v) for v in node]
    return node


def _refs(node: Any, found: set[str]) -> set[str]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for v in node.values():
            _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)
    return found


# ------------------------------------------------------------------------------------------ HTTP
def build_app(data_dir: Path):
    from hydra.api.main import create_app
    from hydra.core.config import Settings

    settings = Settings(offline=True, sandbox_backend="subprocess", workspace_dir=data_dir / "ws",
                        data_dir=data_dir / "data", postgres_url="", redis_url="", nats_url="",
                        api_key="", admin_token="", client_keys_file=data_dir / "clients.json")
    return create_app(settings)


def http_surface(app) -> dict[str, Any]:
    spec = app.openapi()
    operations: dict[str, Any] = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            body = op.get("requestBody", {}).get("content", {})
            operations[f"{method.upper()} {path}"] = _strip_docs({
                "parameters": sorted(({"in": p["in"], "name": p["name"], "required": p.get("required", False),
                                       "schema": p.get("schema", {})} for p in op.get("parameters", [])),
                                     key=lambda p: (p["in"], p["name"])),
                "body": {ctype: c.get("schema", {}) for ctype, c in body.items()},
                "body_required": op.get("requestBody", {}).get("required", False),
                "responses": {code: {ctype: c.get("schema", {}) for ctype, c in r.get("content", {}).items()}
                              for code, r in op.get("responses", {}).items()},
            })
    schemas = spec.get("components", {}).get("schemas", {})
    wanted, frontier = set(), _refs(operations, set())
    while frontier:
        name = frontier.pop()
        if name in wanted or name not in schemas:
            continue
        wanted.add(name)
        frontier |= _refs(schemas[name], set())
    return {"operations": dict(sorted(operations.items())),
            "schemas": {name: _strip_docs(schemas[name]) for name in sorted(wanted)}}


def operation_ids(app) -> list[str]:
    return [op["operationId"] for methods in app.openapi()["paths"].values() for op in methods.values()
            if "operationId" in op]


# ------------------------------------------------------------------------------------------ CLI
def cli_surface(parser: argparse.ArgumentParser) -> dict[str, Any]:
    out: dict[str, Any] = {"arguments": [], "commands": {}}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in sorted(action.choices.items()):
                out["commands"][name] = cli_surface(sub)
            continue
        out["arguments"].append({
            "flags": list(action.option_strings) or [action.dest], "dest": action.dest,
            "required": bool(action.required), "nargs": action.nargs,
            "choices": list(action.choices) if action.choices is not None else None,
            "default": action.default if isinstance(action.default, (str, int, float, bool, type(None)))
            else repr(action.default),
            "kind": type(action).__name__,
        })
    out["arguments"].sort(key=lambda a: a["flags"])
    if not out["commands"]:
        del out["commands"]
    return out


# ------------------------------------------------------------------------------------------ imports
def hydra_imports(path: Path) -> set[tuple[str, str]]:
    """``(module, name)`` pairs a file imports from ``hydra`` (``name`` is ``*`` for ``import module``)."""
    found: set[tuple[str, str]] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                and (node.module == "hydra" or node.module.startswith("hydra.")):
            found |= {(node.module, alias.name) for alias in node.names}
        elif isinstance(node, ast.Import):
            found |= {(alias.name, "*") for alias in node.names if alias.name.startswith("hydra.")}
    return found


def platform_files() -> list[Path]:
    runtime = ROOT / "hydra" / "runtime"
    return sorted(p for p in (ROOT / "hydra").rglob("*.py") if runtime not in p.parents)


def cross_imports() -> dict[str, list[str]]:
    """Platform module -> the ``hydra.runtime`` symbols it imports."""
    out: dict[str, list[str]] = {}
    for path in platform_files():
        names = sorted(f"{m}:{n}" for m, n in hydra_imports(path) if m == "hydra.runtime" or m.startswith("hydra.runtime."))
        if names:
            out[path.relative_to(ROOT).as_posix()] = names
    return out


# ------------------------------------------------------------------------------------------ snapshots
def current() -> dict[str, Any]:
    from hydra.cli import build_parser

    with tempfile.TemporaryDirectory() as tmp:
        app = build_app(Path(tmp))
        http = http_surface(app)
    return {"http.json": http, "cli.json": cli_surface(build_parser()), "cross_imports.json": cross_imports()}


def dump(value: Any) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true", help="rewrite the snapshots in tests/contracts/")
    args = ap.parse_args(argv)
    os.environ.setdefault("HYDRA_RUNTIME_DIR", tempfile.mkdtemp(prefix="hydra-contract-"))
    os.environ["HYDRA_KEY_BACKEND"] = "legacy"
    for token in ("HYDRA_API_KEY", "HYDRA_API_TOKEN", "HYDRA_ADMIN_TOKEN"):
        os.environ[token] = ""
    changed = []
    for name, value in current().items():
        path = HERE / name
        text = dump(value)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            changed.append(name)
            if args.update:
                path.write_text(text, encoding="utf-8")
    print(("updated: " if args.update else "differs: ") + (", ".join(changed) or "nothing"))
    return 0 if args.update or not changed else 1


if __name__ == "__main__":
    sys.exit(main())
