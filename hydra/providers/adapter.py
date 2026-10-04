# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Model Compiler: compile one cognitive intent into the optimal format for each backend.

model A -> native JSON schema          model B -> prompted tool calling
model C -> high reasoning budget       model D -> native images
"""

from __future__ import annotations

import json
import re
from typing import Any

from hydra.core.contracts import ModelRequest, ModelResponse
from hydra.core.errors import ErrorKind, ModelError
from hydra.registry.models import ModelProfile

TOOL_PROMPT = (
    "You can call tools. To call one, reply with ONLY this JSON and nothing else:\n"
    '{{"tool_call": {{"name": "<tool name>", "arguments": {{...}}}}}}\n'
    "Available tools:\n{tools}\n"
    "If no tool is needed, answer normally."
)

SCHEMA_PROMPT = "Reply with ONLY a JSON object (no prose, no code fences) matching this JSON schema:\n{schema}"


def extract_json(text: str) -> Any:
    """First JSON object/array in free text (handles code fences and prose around it)."""
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    for chunk in candidates:
        chunk = chunk.strip()
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            pass
        for opener, closer in (("{", "}"), ("[", "]")):
            start = chunk.find(opener)
            while start != -1:
                depth, in_str, esc = 0, False, False
                for i in range(start, len(chunk)):
                    c = chunk[i]
                    if in_str:
                        esc = (c == "\\") and not esc
                        if c == '"' and not esc:
                            in_str = False
                        continue
                    if c == '"':
                        in_str = True
                    elif c == opener:
                        depth += 1
                    elif c == closer:
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(chunk[start:i + 1])
                            except json.JSONDecodeError:
                                break
                start = chunk.find(opener, start + 1)
    raise json.JSONDecodeError("no JSON found", text, 0)


class ModelCompiler:
    def compile(self, profile: ModelProfile, request: ModelRequest) -> ModelRequest:
        q = profile.quirks
        messages = [dict(m) for m in request.messages]
        meta = dict(request.metadata)
        update: dict[str, Any] = {}
        system_extra: list[str] = []

        if request.response_schema is not None and not q.native_json_schema:
            system_extra.append(SCHEMA_PROMPT.format(schema=json.dumps(request.response_schema)))
            meta["compiled_schema"] = request.response_schema
            update["response_schema"] = None

        if request.tools and not q.native_tools:
            listing = "\n".join(
                f"- {t['function']['name']}: {t['function'].get('description', '')} "
                f"args schema: {json.dumps(t['function'].get('parameters', {}))}"
                for t in request.tools
            )
            system_extra.append(TOOL_PROMPT.format(tools=listing))
            meta["compiled_tools"] = True
            meta["offered_tools"] = [t["function"]["name"] for t in request.tools]
            update["tools"] = None
            # tool results / assistant tool calls must become plain text for such backends
            messages = [self._plain_tool_message(m) for m in messages]

        if not (q.native_images or profile.capabilities.vision >= 0.5):
            for m in messages:
                if m.get("images"):
                    n = len(m.pop("images"))
                    m["content"] = f"{m.get('content', '')}\n[{n} image(s) omitted: model has no vision]"

        if q.prompt_prefix:
            system_extra.insert(0, q.prompt_prefix)
        if system_extra:
            messages = self._add_system(messages, "\n\n".join(system_extra))
        if not q.system_role:
            messages = self._fold_system(messages)

        if q.max_output_tokens:
            update["max_tokens"] = min(request.max_tokens, q.max_output_tokens)
        if q.reasoning_param and request.reasoning_level != "normal":
            meta["reasoning"] = {"param": q.reasoning_param, "level": request.reasoning_level}

        update["messages"] = messages
        update["metadata"] = meta
        return request.model_copy(update=update)

    def decompile(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        meta = request.metadata
        offered = {t["function"]["name"] for t in (request.tools or [])} | set(meta.get("offered_tools", []))
        if (meta.get("compiled_tools") or offered) and not response.tool_calls:
            call = self.textual_tool_call(response.content, offered)
            if call is not None:
                response.tool_calls = [call]
                response.content = ""
        if meta.get("compiled_schema") is not None and response.structured is None:
            try:
                response.structured = extract_json(response.content)
            except json.JSONDecodeError as exc:
                raise ModelError(f"{response.model_id}: invalid JSON output", ErrorKind.INVALID_JSON) from exc
        return response

    @staticmethod
    def textual_tool_call(text: str, offered: set[str]) -> dict | None:
        """Many local models write the call as JSON text instead of native tool_calls:
        {"tool_call": {...}} | {"name": ..., "arguments": ...} | {"function": {...}}."""
        if "{" not in text or not ("name" in text or "tool_call" in text):
            return None
        try:
            data = extract_json(text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            return None
        call = data.get("tool_call") or data.get("function") or data
        if not isinstance(call, dict) or not isinstance(call.get("name"), str):
            return None
        name = call["name"]
        if offered and name not in offered and name.replace(".", "__") not in offered:
            return None
        args = call.get("arguments", call.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        return {"id": None, "name": name, "arguments": args if isinstance(args, dict) else {}}

    @staticmethod
    def _add_system(messages: list[dict], text: str) -> list[dict]:
        if messages and messages[0].get("role") == "system":
            first = dict(messages[0])
            first["content"] = f"{first.get('content', '')}\n\n{text}".strip()
            return [first, *messages[1:]]
        return [{"role": "system", "content": text}, *messages]

    @staticmethod
    def _fold_system(messages: list[dict]) -> list[dict]:
        system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        rest = [dict(m) for m in messages if m.get("role") != "system"]
        if system:
            if rest and rest[0].get("role") == "user":
                rest[0]["content"] = f"{system}\n\n{rest[0]['content']}"
            else:
                rest.insert(0, {"role": "user", "content": system})
        return rest

    @staticmethod
    def _plain_tool_message(m: dict) -> dict:
        if m.get("role") == "tool":
            return {"role": "user", "content": f"TOOL RESULT:\n{m.get('content', '')}"}
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls = [{"name": c["function"]["name"], "arguments": json.loads(c["function"]["arguments"] or "{}")}
                     for c in m["tool_calls"]]
            return {"role": "assistant", "content": json.dumps({"tool_call": calls[0]} if len(calls) == 1
                                                               else {"tool_calls": calls})}
        return m
