# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Deterministic offline provider.

Lets the whole engine run end-to-end without GPUs or runtimes (development,
CI, demos). It understands HYDRA's worker roles and answers in the structured
formats each role expects.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

from hydra.core.contracts import ModelRequest, ModelResponse
from hydra.core.errors import ErrorKind, ModelError
from hydra.providers.base import ModelProvider
from hydra.verification.math_check import ARITH, safe_arith

COLOR_NAMES = {"red": (220, 20, 20), "green": (20, 180, 40), "blue": (30, 60, 220), "white": (245, 245, 245),
               "black": (10, 10, 10), "yellow": (240, 220, 30)}


def dominant_color(data_uri: str) -> str | None:
    """Colour of the first pixel of an 8-bit RGB PNG data URI (enough for offline vision tests)."""
    import base64
    import struct
    import zlib

    try:
        png = base64.b64decode(data_uri.split(",", 1)[1])
        pos, idat = 8, b""
        width = color_type = None
        while pos < len(png):
            length, tag = struct.unpack(">I4s", png[pos:pos + 8])
            data = png[pos + 8:pos + 8 + length]
            if tag == b"IHDR":
                width, _h, _depth, color_type = struct.unpack(">IIBB", data[:10])
            elif tag == b"IDAT":
                idat += data
            pos += 12 + length
        if color_type != 2 or not width:
            return None
        raw = zlib.decompress(idat)
        r, g, b = raw[1], raw[2], raw[3]
    except Exception:
        return None
    return min(COLOR_NAMES, key=lambda n: sum((x - y) ** 2 for x, y in zip(COLOR_NAMES[n], (r, g, b))))


CODE_SYSTEM_HINT = "single ```python code block"
KNOWN_SOLUTIONS = {
    "is_prime": (
        "```python\n"
        "def is_prime(n):\n"
        "    if n < 2:\n"
        "        return False\n"
        "    i = 2\n"
        "    while i * i <= n:\n"
        "        if n % i == 0:\n"
        "            return False\n"
        "        i += 1\n"
        "    return True\n"
        "```"
    ),
    "reverse_words": "```python\ndef reverse_words(s):\n    return ' '.join(reversed(s.split()))\n```",
}

CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)
PATCH_FILE = re.compile(r"### FILE: (\S+)\n```python\n(.*?)```", re.S)
PATCH_RULES = [
    (re.compile(r"(def (?:add|suma|total|plus)\w*\([^)]*\):\s*\n\s*return \w+) - (\w+)"), r"\1 + \2"),
    (re.compile(r"range\(1, (\w+)\)"), r"range(1, \1 + 1)"),
    (re.compile(r"(def (?:is_even|es_par)\w*\([^)]*\):\s*\n\s*return \w+ % 2 ==) 1"), r"\1 0"),
    (re.compile(r"(def (?:maximum|max_of|mayor)\w*\([^)]*\):\s*\n\s*return) min\("), r"\1 max("),
    (re.compile(r"(def (?:average|mean|media)\w*\((\w+)\):\s*\n\s*return sum\(\2\)) / \(len\(\2\) - 1\)"),
     r"\1 / len(\2)"),
    (re.compile(r"\.sort\(reverse=True\)(\s*#\s*ascending)"), r".sort()\1"),
]


class MockProvider(ModelProvider):
    def __init__(
        self,
        latency_ms: dict[str, float] | None = None,
        fail: dict[str, ErrorKind] | None = None,
        quality: dict[str, float] | None = None,
    ) -> None:
        self.latency_ms = latency_ms or {}
        self.fail = fail or {}
        self.quality = quality or {}
        self.calls: list[tuple[str, str]] = []

    async def generate(self, model_id: str, request: ModelRequest) -> ModelResponse:
        role = request.metadata.get("role", "reasoner")
        self.calls.append((model_id, role))
        started = time.perf_counter()
        delay = self.latency_ms.get(model_id, 5)
        await asyncio.sleep(delay / 1000)
        if model_id in self.fail:
            raise ModelError(f"{model_id}: simulated failure", self.fail[model_id])

        user = next((m["content"] for m in reversed(request.messages) if m["role"] == "user"), "")
        tool_msgs = [m for m in request.messages if m["role"] == "tool"]

        structured = None
        tool_calls: list[dict] = []
        if "HYDRA_PATCH_REQUEST" in user and request.response_schema is None:
            content = self._patch(user)
        elif request.response_schema is not None:
            structured = self._structured(role, user, request)
            content = json.dumps(structured, ensure_ascii=False)
        elif request.tools and not tool_msgs and ((code := CODE_BLOCK.search(user)) or "tool" in user.lower()):
            names = {t["function"]["name"].replace("__", ".") for t in request.tools}
            if "python.execute" in names:
                src = code.group(1) if code else "print(sum(i * i for i in range(1, 101)))"
                tool_calls = [{"id": "call_1", "name": "python.execute", "arguments": {"code": src}}]
            content = ""
        else:
            content = self._answer(model_id, role, user, tool_msgs, request)

        tokens_in = sum(len(str(m.get("content", ""))) for m in request.messages) // 4
        return ModelResponse(
            model_id=model_id,
            content=content,
            latency_ms=(time.perf_counter() - started) * 1000,
            input_tokens=tokens_in,
            output_tokens=len(content) // 4,
            tool_calls=tool_calls,
            structured=structured,
        )

    def _answer(self, model_id: str, role: str, user: str, tool_msgs: list[dict], request: ModelRequest) -> str:
        if role == "synthesizer":
            return self._synthesis(user)
        images = [i for m in request.messages for i in (m.get("images") or [])]
        if images and (color := dominant_color(images[0])):
            return f"The image is {color}."
        system = "\n".join(str(m.get("content", "")) for m in request.messages if m["role"] == "system")
        if seen := re.search(r"\[perception\] ([^\n]+)", system):
            return f"Observación visual: {seen.group(1)}."
        if CODE_SYSTEM_HINT in system and (fn := re.search(r"function (\w+)\(", user)):
            return KNOWN_SOLUTIONS.get(
                fn.group(1), f"```python\ndef {fn.group(1)}(*a):\n    raise NotImplementedError\n```")
        if tool_msgs:
            outputs = "\n".join(str(m["content"]) for m in tool_msgs)
            return f"He ejecutado el código en el sandbox. Resultado:\n{outputs.strip()}"
        if m := ARITH.search(user):
            value = safe_arith(m.group(1))
            if value is not None:
                if isinstance(value, float) and value.is_integer():
                    value = int(value)
                return f"{m.group(1).strip()} = {value}"
        return f"[{model_id}] Respuesta a: {user.strip()[:400]}"

    @staticmethod
    def _patch(prompt: str) -> str:
        """Deterministic 'fixes' for the offline debugging suites (a test double, not intelligence)."""
        out = []
        for m in PATCH_FILE.finditer(prompt):
            path, body = m.group(1), m.group(2)
            if re.search(r"(^|/)test_[^/]*\.py$|_test\.py$", path):
                continue
            fixed = body
            for rx, rep in PATCH_RULES:
                fixed = rx.sub(rep, fixed)
            if fixed != body:
                out.append(f"### FILE: {path}\n```python\n{fixed}```")
        return "\n\n".join(out) or "No change needed."

    @staticmethod
    def _synthesis(prompt: str) -> str:
        match = re.search(r"CONCLUSIONS:\n(.*?)(?:\nUNCERTAINTIES:|\Z)", prompt, re.S)
        body = match.group(1).strip() if match else prompt.strip()
        body = re.sub(r"^- ", "", body, flags=re.M)
        return body

    def _structured(self, role: str, user: str, request: ModelRequest) -> dict:
        if role == "router":
            text = user.lower()
            task = "coding" if any(k in text for k in ("python", "code", "código", "bug")) else "chat"
            return {"task_type": task, "complexity": 0.4, "risk": 0.1}
        if role == "critic":
            score = self.quality.get("critic", 0.85)
            return {"verdict": "pass" if score >= 0.5 else "fail", "score": score,
                    "issues": [] if score >= 0.5 else ["the answer is not supported by the evidence"]}
        if role == "judge":
            n = user.count("### CANDIDATE")
            return {
                "best_index": 0,
                "agreement": 0.9 if n > 1 else 1.0,
                "common_facts": [],
                "disagreements": [],
                "merged_answer": None,
            }
        if role == "memory_extract":
            return {"facts": [], "procedure": None}
        if role == "vision":
            images = [i for m in request.messages for i in (m.get("images") or [])]
            colors = [c for c in (dominant_color(i) for i in images) if c]
            return {
                "description": f"a solid {colors[0]} square" if colors else "an image",
                "objects": [{"name": "square", "type": "shape", "attributes": {"color": c}} for c in colors[:1]],
                "relations": [], "text": [],
            }
        if role == "researcher":
            parts = [p.strip(" ?¿") for p in re.split(r"\?|;|\n| y además | and also ", user) if len(p.strip()) > 12]
            return {"subquestions": [p + "?" for p in parts[:4]] or [user]}
        if role in ("claim_verifier", "eval"):
            return {"verdict": "supported", "correction": None, "reason": "consistent"}
        return {}

    async def health(self) -> bool:
        return True
