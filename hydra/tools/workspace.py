# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Workspace Manager + repository tools + structured test runs.

    /workspaces/{task_id}/
    ├── input/      read-only source snapshot
    ├── working/    mutable working copy (tools write here; may disappear at the end)
    ├── outputs/    patch.diff, tests.json, reports (kept)
    └── metadata/   manifest, hashes

Tool results are structured (``TestRunResult``), not only stdout, which makes
verification and later tool-router training much easier."""

from __future__ import annotations

import asyncio
import difflib
import fnmatch
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.hashing import now_iso, sha256_file
from hydra.tools.definitions import RegisteredTool, ToolContext, ToolDefinition
from hydra.tools.policy import allowed_path
from hydra.tools.registry import ToolRegistry
from hydra.tools.sandbox import Sandbox

IGNORE = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache", ".idea", ".tox"}
MAX_SNAPSHOT_BYTES = 200 * 1024 * 1024


class Workspace(BaseModel):
    task_id: str
    root: Path
    source: str | None = None
    created_at: str = Field(default_factory=now_iso)

    @property
    def input(self) -> Path:
        return self.root / "input"

    @property
    def working(self) -> Path:
        return self.root / "working"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def metadata(self) -> Path:
        return self.root / "metadata"


MAX_SNAPSHOT_FILES = 20_000
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def scan_source(source: Path, blocked: set[str] = IGNORE, *, max_files: int = MAX_SNAPSHOT_FILES,
                max_bytes: int = MAX_SNAPSHOT_BYTES) -> tuple[int, int]:
    """Reject symlinks, non-regular files and oversized trees before anything is copied.

    Returns ``(files, bytes)``. Blocked directory names are skipped, never traversed."""
    if source.is_symlink():
        raise ValueError("Workspace source may not be a symlink")
    files = total = 0
    for directory, dirnames, filenames in os.walk(source, followlinks=False):
        here = Path(directory)
        kept = []
        for name in dirnames:
            if (here / name).is_symlink():
                raise ValueError(f"Workspace source contains symlink: {here / name}")
            if name not in blocked:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            if name in blocked:
                continue
            path = here / name
            if path.is_symlink():
                raise ValueError(f"Workspace source contains symlink: {path}")
            if not path.is_file():
                raise ValueError(f"Workspace source contains non-regular file: {path}")
            files += 1
            total += path.stat().st_size
            if files > max_files:
                raise ValueError("Workspace source exceeds maximum file count")
            if total > max_bytes:
                raise ValueError(f"Workspace source exceeds maximum byte size ({max_bytes // 2**20} MB)")
    return files, total


def validate_no_symlinks(root: Path) -> None:
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f"Copied workspace contains symlink: {Path(directory) / name}")


def contained(base: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``base``; reject absolute paths and ``..`` escapes."""
    target = (base / rel).resolve()
    if target != base.resolve() and base.resolve() not in target.parents:
        raise ValueError(f"path escapes workspace: {rel}")
    return target


def _copy(src: Path, dst: Path) -> int:
    _, total = scan_source(src)

    def ignore(d, names):
        return [n for n in names if n in IGNORE]

    shutil.copytree(src, dst, ignore=ignore, symlinks=True, dirs_exist_ok=True)
    validate_no_symlinks(dst)
    return total


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def create(self, task_id: str, source: Path | None = None, files: dict[str, str] | None = None) -> Workspace:
        if not _TASK_ID.match(task_id):
            raise ValueError(f"invalid task id for workspace: {task_id!r}")
        ws = Workspace(task_id=task_id, root=self.root / task_id, source=str(source) if source else None)
        for d in (ws.input, ws.working, ws.outputs, ws.metadata):
            d.mkdir(parents=True, exist_ok=True)
        if source is not None:
            _copy(source, ws.input)
        for rel, content in (files or {}).items():
            p = contained(ws.input, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        shutil.copytree(ws.input, ws.working, dirs_exist_ok=True)
        (ws.metadata / "workspace.json").write_text(ws.model_dump_json(indent=2), encoding="utf-8")
        return ws

    def get(self, task_id: str) -> Workspace | None:
        if not _TASK_ID.match(task_id):
            return None
        p = self.root / task_id / "metadata" / "workspace.json"
        return Workspace.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None

    @staticmethod
    def diff(ws: Workspace) -> str:
        out = []
        files = {p.relative_to(ws.input).as_posix() for p in ws.input.rglob("*") if p.is_file()}
        files |= {p.relative_to(ws.working).as_posix() for p in ws.working.rglob("*") if p.is_file()}
        for rel in sorted(files):
            if any(part in IGNORE for part in Path(rel).parts):
                continue
            a, b = ws.input / rel, ws.working / rel
            try:
                la = a.read_text(encoding="utf-8").splitlines(keepends=True) if a.exists() else []
                lb = b.read_text(encoding="utf-8").splitlines(keepends=True) if b.exists() else []
            except UnicodeDecodeError:
                continue
            if la != lb:
                out.extend(difflib.unified_diff(la, lb, f"a/{rel}", f"b/{rel}"))
        return "".join(out)

    def finalize(self, ws: Workspace, keep_working: bool = False, extra: dict[str, Any] | None = None
                 ) -> dict[str, Any]:
        patch = self.diff(ws)
        (ws.outputs / "patch.diff").write_text(patch, encoding="utf-8")
        if extra:
            (ws.outputs / "result.json").write_text(json.dumps(extra, indent=2, default=str), encoding="utf-8")
        hashes = {p.relative_to(ws.root).as_posix(): sha256_file(p) for p in ws.outputs.rglob("*") if p.is_file()}
        (ws.metadata / "hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
        if not keep_working:
            shutil.rmtree(ws.working, ignore_errors=True)
        return {"patch_bytes": len(patch.encode()), "files_changed": patch.count("\n+++ b/") + patch.startswith("+++ b/"),
                "outputs": sorted(hashes)}


# ------------------------------------------------------------------------------ structured tests
class TestFailure(BaseModel):
    test: str
    message: str


class TestRunResult(BaseModel):
    success: bool
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    failures: list[TestFailure] = Field(default_factory=list)
    runner: str = "builtin"
    duration_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


TEST_RUNNER = r'''
import sys, os, json, traceback, importlib.util, glob, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.getcwd())
res = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "failures": [], "runner": "builtin"}
pattern = %(pattern)r
started = time.time()
try:
    import pytest
    class P:
        def pytest_collectreport(self, report):
            if report.failed:
                res["errors"] += 1
                res["failures"].append({"test": report.nodeid or "collection", "message": str(report.longrepr)[-800:]})
        def pytest_runtest_logreport(self, report):
            if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
                if report.passed and report.when == "call": res["passed"] += 1
                elif report.skipped: res["skipped"] += 1
                elif report.failed:
                    res["failed" if report.when == "call" else "errors"] += 1
                    res["failures"].append({"test": report.nodeid, "message": str(report.longrepr)[-800:]})
    res["runner"] = "pytest"
    code = pytest.main(["-q", "-p", "no:cacheprovider", "-p", "no:warnings", "-c", os.devnull, "--rootdir", os.getcwd(),
                        "-o", "addopts="] + ([pattern] if pattern else ["."]), plugins=[P()])
    if int(code) not in (0, 5) and res["failed"] + res["errors"] == 0:
        res["errors"] += 1
        res["failures"].append({"test": "pytest", "message": "pytest exit code " + str(int(code))})
except ImportError:
    files = sorted(set(glob.glob("**/test_*.py", recursive=True) + glob.glob("**/*_test.py", recursive=True)))
    if pattern:
        files = [f for f in files if pattern in f]
    for f in files:
        name = "hydra_t_" + f.replace("/", "_").replace("\\", "_")[:-3]
        try:
            spec = importlib.util.spec_from_file_location(name, f)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        except Exception as e:
            res["errors"] += 1; res["failures"].append({"test": f, "message": "import error: " + repr(e)[:600]}); continue
        for attr in sorted(dir(mod)):
            fn = getattr(mod, attr)
            if attr.startswith("test") and callable(fn):
                try:
                    fn(); res["passed"] += 1
                except AssertionError as e:
                    res["failed"] += 1; res["failures"].append({"test": f + "::" + attr, "message": ("AssertionError " + str(e))[:600] + "\n" + traceback.format_exc()[-600:]})
                except Exception as e:
                    res["failed"] += 1; res["failures"].append({"test": f + "::" + attr, "message": repr(e)[:600]})
res["duration_ms"] = round((time.time() - started) * 1000, 1)
res["success"] = res["failed"] == 0 and res["errors"] == 0 and res["passed"] > 0
print("HYDRA_TEST_RESULT:" + json.dumps(res))
'''


async def run_tests(sandbox: Sandbox, workdir: Path, pattern: str | None = None, timeout: int = 120
                    ) -> TestRunResult:
    r = await sandbox.execute_python(TEST_RUNNER % {"pattern": pattern or ""}, timeout=timeout, workdir=workdir)
    m = re.search(r"HYDRA_TEST_RESULT:(\{.*\})", r.stdout)
    if not m:
        return TestRunResult(success=False, errors=1, stdout=r.stdout[-4000:], stderr=r.stderr[-4000:],
                             exit_code=r.exit_code, failures=[TestFailure(test="runner", message=r.stderr[-800:])])
    data = json.loads(m.group(1))
    return TestRunResult(**{k: v for k, v in data.items() if k in TestRunResult.model_fields},
                         stdout=r.stdout[-4000:], stderr=r.stderr[-2000:], exit_code=r.exit_code)


# ------------------------------------------------------------------------------ tools
def _obj(props: dict[str, Any], required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _root(ctx: ToolContext) -> Path:
    p = allowed_path(ctx, ".")
    if p is None:
        raise PermissionError("no workspace")
    return p


async def workspace_list(args: dict, ctx: ToolContext) -> dict:
    root = _root(ctx)
    pattern = args.get("pattern", "*")

    def walk():
        out = []
        for p in sorted(root.rglob("*")):
            if p.is_file() and not any(part in IGNORE for part in p.relative_to(root).parts):
                rel = p.relative_to(root).as_posix()
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern):
                    out.append({"path": rel, "bytes": p.stat().st_size})
            if len(out) >= int(args.get("limit", 500)):
                break
        return out
    return {"files": await asyncio.to_thread(walk)}


async def workspace_search(args: dict, ctx: ToolContext) -> dict:
    root = _root(ctx)
    rx = re.compile(args["query"] if args.get("regex") else re.escape(args["query"]), re.I)

    def scan():
        hits = []
        for p in sorted(root.rglob("*")):
            if not p.is_file() or any(part in IGNORE for part in p.relative_to(root).parts) or p.stat().st_size > 1e6:
                continue
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                    if rx.search(line):
                        hits.append({"path": p.relative_to(root).as_posix(), "line": i, "text": line.strip()[:300]})
                        if len(hits) >= int(args.get("limit", 100)):
                            return hits
            except (UnicodeDecodeError, OSError):
                continue
        return hits
    return {"matches": await asyncio.to_thread(scan)}


def python_run_tests(sandbox: Sandbox):
    async def handler(args: dict, ctx: ToolContext) -> dict:
        timeout = min(int(args.get("timeout", 120)), max(ctx.capabilities.max_runtime_seconds, 30))
        res = await run_tests(sandbox, _root(ctx), args.get("pattern"), timeout)
        d = res.model_dump()
        d["exit_code"] = 0 if res.success else 1
        return d
    return handler


def register_workspace_tools(registry: ToolRegistry, sandbox: Sandbox) -> None:
    defs = [
        (ToolDefinition(name="workspace.list", description="List files of the task workspace (glob pattern).",
                        input_schema=_obj({"pattern": {"type": "string"},
                                           "limit": {"type": "integer", "minimum": 1, "maximum": 5000}}, []),
                        timeout_seconds=10, requires_filesystem=True), workspace_list),
        (ToolDefinition(name="workspace.search", description="Search text (or regex) in the task workspace files.",
                        input_schema=_obj({"query": {"type": "string"}, "regex": {"type": "boolean"},
                                           "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}, ["query"]),
                        timeout_seconds=20, requires_filesystem=True), workspace_search),
        (ToolDefinition(name="python.run_tests",
                        description="Run the workspace test-suite in the sandbox (pytest if available). Returns "
                                    "structured results: passed, failed, failures[].",
                        input_schema=_obj({"pattern": {"type": "string"},
                                           "timeout": {"type": "integer", "minimum": 5, "maximum": 600}}, []),
                        timeout_seconds=620, risk_level=2, requires_filesystem=True), python_run_tests(sandbox)),
    ]
    for d, h in defs:
        registry.register(RegisteredTool(d, h))
