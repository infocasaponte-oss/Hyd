# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F0 guards for the unification of the platform and runtime lines: the HTTP API, the CLI and every
``hydra`` symbol used by the engine, the model factory and the scripts must keep existing while
duplicates are removed (docs/PLAN_UNIFICACION_LINEAS_2026-10-01.md). Regenerate after an intended
change with ``python -m tests.contracts.surface --update``."""
from __future__ import annotations

import ast
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

import pytest

from hydra.cli import build_parser
from tests.contracts.surface import (
    HERE,
    ROOT,
    build_app,
    cli_surface,
    cross_imports,
    dump,
    http_surface,
    hydra_imports,
    operation_ids,
    platform_files,
)

REGENERATE = "if the change is intended: python -m tests.contracts.surface --update"


def _snapshot(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    return build_app(tmp_path_factory.mktemp("contract"))


def test_http_api_contract(app):
    want, got = _snapshot("http.json"), json.loads(dump(http_surface(app)))
    removed = sorted(set(want["operations"]) - set(got["operations"]))
    added = sorted(set(got["operations"]) - set(want["operations"]))
    changed = sorted(k for k in set(want["operations"]) & set(got["operations"])
                     if want["operations"][k] != got["operations"][k])
    schemas = sorted(k for k in set(want["schemas"]) | set(got["schemas"])
                     if want["schemas"].get(k) != got["schemas"].get(k))
    assert not (removed or added or changed or schemas), (
        f"HTTP API changed. removed={removed} added={added} changed={changed} schemas={schemas}; {REGENERATE}")


def test_operation_ids_are_unique(app):
    ids = operation_ids(app)
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_cli_contract():
    want, got = _snapshot("cli.json"), json.loads(dump(cli_surface(build_parser())))
    removed = sorted(set(want["commands"]) - set(got["commands"]))
    changed = sorted(c for c in set(want["commands"]) & set(got["commands"]) if want["commands"][c] != got["commands"][c])
    assert want == got, f"CLI changed. removed={removed} changed={changed}; {REGENERATE}"


def test_platform_imports_from_the_runtime_line_only_shrink():
    allowed = _snapshot("cross_imports.json")
    new = {f: sorted(set(names) - set(allowed.get(f, []))) for f, names in cross_imports().items()}
    new = {f: names for f, names in new.items() if names}
    assert not new, f"new platform -> hydra.runtime imports (plan principle 6): {new}"


# ------------------------------------------------------------------------------------------ symbols
@lru_cache(maxsize=None)
def _module_file(module: str) -> Path | None:
    parts = module.split(".")
    base = ROOT.joinpath(*parts)
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=None)
def _defined_names(module: str) -> frozenset[str] | None:
    """Top-level names a module defines or re-exports (None: it star-imports, anything may exist)."""
    path = _module_file(module)
    if path is None:
        return frozenset()
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        for n in ([node] if not isinstance(node, (ast.If, ast.Try)) else
                  [*node.body, *getattr(node, "orelse", []), *[h for t in getattr(node, "handlers", []) for h in t.body],
                   *getattr(node, "finalbody", [])]):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
            elif isinstance(n, ast.Assign):
                names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
                names |= {e.id for t in n.targets if isinstance(t, ast.Tuple) for e in t.elts if isinstance(e, ast.Name)}
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                names.add(n.target.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                if any(a.name == "*" for a in n.names):
                    return None
                names |= {(a.asname or a.name).split(".")[0] for a in n.names}
    return frozenset(names)


def _resolves(module: str, name: str) -> bool:
    if _module_file(module) is None:
        return importlib.util.find_spec(module) is not None if not module.startswith("hydra") else False
    if name == "*":
        return True
    defined = _defined_names(module)
    return defined is None or name in defined or _module_file(f"{module}.{name}") is not None


def _consumers() -> list[Path]:
    return [*platform_files(), *sorted((ROOT / "hydra" / "runtime").glob("*.py")), *sorted((ROOT / "scripts").glob("*.py"))]


def test_every_hydra_symbol_used_by_engine_factory_and_scripts_exists():
    """Static check (no import, so optional dependencies such as torch are not needed): removing a
    duplicate must leave every name its users import resolvable, in the engine and in the factory."""
    missing = sorted(f"{p.relative_to(ROOT).as_posix()}: {m}.{n}" for p in _consumers()
                     for m, n in hydra_imports(p) if not _resolves(m, n))
    assert not missing, "unresolvable hydra imports:\n" + "\n".join(missing)
