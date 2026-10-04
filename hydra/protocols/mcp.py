# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Model Context Protocol (MCP) interoperability: server and client.

Server: exposes HYDRA's tools (through the Policy Kernel / tool executor) plus meta-tools
(``hydra_ask``, ``hydra_world_query``, ``hydra_corpus_search``) over JSON-RPC 2.0, via stdio
(``hydra mcp``) or HTTP (``POST /mcp``). Client: consumes external MCP servers (stdio) and
registers their tools as ``mcp.<server>.<tool>`` HYDRA tools (confirmation required by
default: external tools are untrusted). The internal protocol stays stable whatever the
external protocol versions do."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from uuid import uuid4

import hydra
from hydra.core.contracts import HydraRequest, Message
from hydra.tools.definitions import RegisteredTool, ToolCall, ToolContext, ToolDefinition, WorkerCapabilities
from hydra.tools.registry import to_function_name

SUPPORTED_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"]
LATEST = SUPPORTED_VERSIONS[-1]

META_TOOLS = [
    {"name": "hydra_ask", "description": "Ask HYDRA (routing, verification, provenance). Returns the verified answer.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string"},
                                                      "mode": {"type": "string", "enum": ["fast", "balanced", "deep",
                                                                                          "private"]}},
                     "required": ["question"]}},
    {"name": "hydra_world_query", "description": "Query HYDRA's World Model (verified facts, contested beliefs).",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "hydra_corpus_search", "description": "Search HYDRA's curated corpus.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "limit": {"type": "integer"}},
                     "required": ["text"]}},
]


def _err(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


class MCPServer:
    def __init__(self, runtime, expose_tools: set[str] | None = None) -> None:
        self.rt = runtime
        self.expose = expose_tools or {"python.execute", "json.validate", "search.query", "workspace.list",
                                       "workspace.search", "python.run_tests"}
        self.version = LATEST

    def _tools(self) -> list[dict[str, Any]]:
        out = list(META_TOOLS)
        for name, t in self.rt.tools.tools.items():
            if name in self.expose:
                out.append({"name": to_function_name(name), "description": t.definition.description,
                            "inputSchema": t.definition.input_schema,
                            "annotations": {"readOnlyHint": not t.definition.writes,
                                            "destructiveHint": t.definition.writes,
                                            "openWorldHint": t.definition.requires_network}})
        return out

    async def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        id_, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
        if msg.get("jsonrpc") != "2.0":
            return _err(id_, -32600, "invalid request")
        if id_ is None:  # notification
            return None
        try:
            if method == "initialize":
                req = params.get("protocolVersion", LATEST)
                self.version = req if req in SUPPORTED_VERSIONS else LATEST
                return {"jsonrpc": "2.0", "id": id_, "result": {
                    "protocolVersion": self.version,
                    "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False},
                                     "prompts": {"listChanged": False}},
                    "serverInfo": {"name": "hydra", "title": "HYDRA OS", "version": hydra.__version__},
                    "instructions": "HYDRA cognitive OS. Tool calls pass through HYDRA's Policy Kernel."}}
            if method == "ping":
                return {"jsonrpc": "2.0", "id": id_, "result": {}}
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": id_, "result": {"tools": self._tools()}}
            if method == "tools/call":
                return {"jsonrpc": "2.0", "id": id_, "result": await self._call(params.get("name", ""),
                                                                                params.get("arguments") or {})}
            if method == "resources/list":
                return {"jsonrpc": "2.0", "id": id_, "result": {"resources": [
                    {"uri": "hydra://world/stats", "name": "World Model statistics", "mimeType": "application/json"},
                    {"uri": "hydra://corpus/stats", "name": "Corpus statistics", "mimeType": "application/json"},
                    {"uri": "hydra://ledger/verify", "name": "Ledger integrity", "mimeType": "application/json"}]}}
            if method == "resources/read":
                uri = params.get("uri", "")
                data = {"hydra://world/stats": lambda: self.rt.world.stats(),
                        "hydra://corpus/stats": lambda: self.rt.corpus.stats(),
                        "hydra://ledger/verify": lambda: self.rt.ledger.verify().model_dump()}.get(uri)
                if data is None:
                    return _err(id_, -32602, f"unknown resource {uri}")
                return {"jsonrpc": "2.0", "id": id_, "result": {"contents": [
                    {"uri": uri, "mimeType": "application/json", "text": json.dumps(data(), default=str)}]}}
            if method == "prompts/list":
                return {"jsonrpc": "2.0", "id": id_, "result": {"prompts": []}}
            return _err(id_, -32601, f"method not found: {method}")
        except Exception as exc:
            return _err(id_, -32603, f"{type(exc).__name__}: {exc}")

    async def _call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "hydra_ask":
            r = await self.rt.kernel.run(HydraRequest(messages=[Message(role="user", content=args["question"])],
                                                      mode=args.get("mode", "balanced")))
            return {"content": [{"type": "text", "text": r.answer}],
                    "structuredContent": {"confidence": r.meta.confidence, "verified": r.meta.verified,
                                          "task_id": r.meta.task_id, "models": r.meta.models_used},
                    "isError": False}
        if name == "hydra_world_query":
            pkt = self.rt.world_rag.packet(args["query"])
            return {"content": [{"type": "text", "text": pkt.render() or "(no knowledge)"}],
                    "structuredContent": pkt.model_dump(mode="json"), "isError": False}
        if name == "hydra_corpus_search":
            recs = self.rt.corpus.search(text=args["text"], statuses={"CURATED", "GOLD"},
                                         limit=int(args.get("limit", 10)))
            items = [{"id": r.id, "type": r.record_type.value, "quality": r.quality,
                      "input": r.input, "output": {k: str(v)[:500] for k, v in r.output.items()}} for r in recs]
            return {"content": [{"type": "text", "text": json.dumps(items, ensure_ascii=False)[:20000]}],
                    "structuredContent": {"records": items}, "isError": False}
        tool = self.rt.tools.get(name)
        if tool is None or tool.definition.name not in self.expose:
            return {"content": [{"type": "text", "text": f"unknown or unexposed tool {name}"}], "isError": True}
        ctx = ToolContext(task_id=uuid4(), capabilities=WorkerCapabilities(tools=set(self.expose),
                                                                           filesystem_paths=["."],
                                                                           max_runtime_seconds=120),
                          workspace=self.rt.settings.workspace_dir)
        res = await self.rt.executor.execute(ToolCall(name=tool.definition.name, arguments=args,
                                                      requested_by="mcp-client"), ctx)
        text = json.dumps(res.output, ensure_ascii=False, default=str) if res.success else (res.error or "failed")
        return {"content": [{"type": "text", "text": text[:50000]}],
                "structuredContent": res.output if isinstance(res.output, dict) else None, "isError": not res.success}

    async def serve_stdio(self) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        while line := await reader.readline():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps(_err(None, -32700, "parse error")) + "\n")
                sys.stdout.flush()
                continue
            resp = await self.handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, default=str) + "\n")
                sys.stdout.flush()


class MCPClient:
    """Minimal stdio MCP client: launch an external server, list and call its tools."""

    def __init__(self, command: list[str], name: str) -> None:
        self.command = command
        self.name = name
        self.proc: asyncio.subprocess.Process | None = None
        self._id = 0
        self.tools: list[dict[str, Any]] = []
        self.server_info: dict[str, Any] = {}

    async def _rpc(self, method: str, params: dict | None = None, notify: bool = False) -> Any:
        assert self.proc and self.proc.stdin and self.proc.stdout
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()
        if notify:
            return None
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=60)
            if not line:
                raise ConnectionError(f"MCP server {self.name} closed")
            resp = json.loads(line)
            if resp.get("id") == msg["id"]:
                if "error" in resp:
                    raise RuntimeError(resp["error"].get("message"))
                return resp.get("result")

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(*self.command, stdin=asyncio.subprocess.PIPE,
                                                         stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.DEVNULL)
        init = await self._rpc("initialize", {"protocolVersion": LATEST, "capabilities": {},
                                              "clientInfo": {"name": "hydra", "version": hydra.__version__}})
        self.server_info = init.get("serverInfo", {})
        await self._rpc("notifications/initialized", notify=True)
        self.tools = (await self._rpc("tools/list")).get("tools", [])

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._rpc("tools/call", {"name": tool, "arguments": arguments})

    async def close(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()

    def register(self, registry, risk_level: int = 3) -> list[str]:
        names = []
        for t in self.tools:
            full = f"mcp.{self.name}.{t['name']}"

            async def handler(args: dict, ctx: ToolContext, _t=t["name"]) -> dict:
                res = await self.call(_t, args)
                return {"content": res.get("content"), "structured": res.get("structuredContent"),
                        "exit_code": 1 if res.get("isError") else 0}
            registry.register(RegisteredTool(ToolDefinition(
                name=full, description=f"[MCP {self.name}] {t.get('description', '')}"[:500],
                input_schema=t.get("inputSchema") or {"type": "object"}, timeout_seconds=60, risk_level=risk_level,
                requires_network=True), handler))
            names.append(full)
        return names
