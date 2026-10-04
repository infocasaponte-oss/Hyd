# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import sqlite3
from uuid import uuid4

import pytest

from hydra.bus.memory import InMemoryEventBus
from hydra.core.events import EventType
from hydra.tools.builtin import register_builtin_tools
from hydra.tools.definitions import ToolCall, ToolContext, WorkerCapabilities
from hydra.tools.executor import ToolExecutor
from hydra.tools.policy import ToolPolicyEngine
from hydra.tools.registry import ToolRegistry
from hydra.tools.sandbox import DockerSandbox, SubprocessSandbox

ALL = {"python.execute", "filesystem.read", "filesystem.write", "http.fetch", "json.validate",
       "sql.query_readonly", "git.diff", "git.apply_patch"}


@pytest.fixture
def setup(tmp_path):
    bus = InMemoryEventBus()
    reg = register_builtin_tools(ToolRegistry(), SubprocessSandbox())
    ex = ToolExecutor(reg, ToolPolicyEngine(), bus)

    def ctx(tools=ALL, **kw):
        return ToolContext(task_id=uuid4(), workspace=tmp_path,
                           capabilities=WorkerCapabilities(tools=set(tools), filesystem_paths=["."],
                                                           network_domains=["example.com"],
                                                           max_runtime_seconds=30), **kw)
    return ex, ctx, bus, tmp_path


async def test_python_sandbox_runs_code(setup):
    ex, ctx, bus, _ = setup
    c = ctx()
    r = await ex.execute(ToolCall(name="python.execute", arguments={"code": "print(6*7)"}), c)
    assert r.success and r.output["stdout"].strip() == "42"
    types = [e.type for e in await bus.history(c.task_id)]
    assert types == [EventType.TOOL_REQUESTED, EventType.TOOL_STARTED, EventType.TOOL_COMPLETED]


async def test_python_sandbox_timeout(setup):
    ex, ctx, _, _ = setup
    r = await ex.execute(ToolCall(name="python.execute",
                                  arguments={"code": "while True: pass", "timeout": 1}), ctx())
    assert not r.success and r.output["timed_out"]


async def test_capability_not_granted_is_denied(setup):
    ex, ctx, bus, _ = setup
    c = ctx(tools={"json.validate"})
    r = await ex.execute(ToolCall(name="python.execute", arguments={"code": "print(1)"}), c)
    assert not r.success and "not granted" in r.error
    assert (await bus.history(c.task_id))[-1].type == EventType.TOOL_DENIED


async def test_private_mode_blocks_network(setup):
    ex, ctx, _, _ = setup
    r = await ex.execute(ToolCall(name="http.fetch", arguments={"url": "https://example.com"}), ctx(private=True))
    assert not r.success and "private" in r.error


async def test_domain_allowlist(setup):
    ex, ctx, _, _ = setup
    r = await ex.execute(ToolCall(name="http.fetch", arguments={"url": "https://evil.test/x"}), ctx())
    assert not r.success and "domain" in r.error


async def test_path_escape_blocked_and_scoped_io(setup):
    ex, ctx, _, ws = setup
    c = ctx()
    r = await ex.execute(ToolCall(name="filesystem.read", arguments={"path": "../../etc/passwd"}), c)
    assert not r.success and "outside" in r.error
    w = await ex.execute(ToolCall(name="filesystem.write", arguments={"path": "a/b.txt", "content": "hola"}), c)
    assert w.success and (ws / "a" / "b.txt").read_text() == "hola"
    r = await ex.execute(ToolCall(name="filesystem.read", arguments={"path": "a/b.txt"}), c)
    assert r.output["content"] == "hola"


async def test_schema_validation_and_hallucinated_tool(setup):
    ex, ctx, _, _ = setup
    r = await ex.execute(ToolCall(name="python.execute", arguments={"cmd": "rm -rf /"}), ctx())
    assert not r.success and "invalid arguments" in r.error
    r = await ex.execute(ToolCall(name="shell.root", arguments={}), ctx())
    assert not r.success and "unknown tool" in r.error


async def test_sql_readonly(setup):
    ex, ctx, _, ws = setup
    con = sqlite3.connect(ws / "db.sqlite")
    con.execute("CREATE TABLE t (x INT)")
    con.execute("INSERT INTO t VALUES (1), (2)")
    con.commit()
    con.close()
    c = ctx()
    r = await ex.execute(ToolCall(name="sql.query_readonly",
                                  arguments={"database": "db.sqlite", "query": "SELECT sum(x) FROM t"}), c)
    assert r.success and r.output["rows"] == [[3]]
    r = await ex.execute(ToolCall(name="sql.query_readonly",
                                  arguments={"database": "db.sqlite", "query": "DELETE FROM t"}), c)
    assert not r.success


async def test_json_validate(setup):
    ex, ctx, _, _ = setup
    r = await ex.execute(ToolCall(name="json.validate", arguments={
        "document": {"a": "x"}, "schema": {"type": "object", "properties": {"a": {"type": "integer"}}}}), ctx())
    assert r.success and not r.output["valid"]


def test_function_names_have_no_dots():
    reg = register_builtin_tools(ToolRegistry(), SubprocessSandbox())
    names = [s["function"]["name"] for s in reg.specs()]
    assert all("." not in n for n in names)
    assert reg.get("python__execute").definition.name == "python.execute"


def test_docker_sandbox_is_locked_down():
    cmd = DockerSandbox().command("x")
    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL", "--memory", "--pids-limit", "--rm"):
        assert flag in cmd
