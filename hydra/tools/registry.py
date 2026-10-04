# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from hydra.tools.definitions import RegisteredTool

# OpenAI-style function names cannot contain dots.
_SEP = "__"


def to_function_name(tool_name: str) -> str:
    return tool_name.replace(".", _SEP)


def from_function_name(function_name: str) -> str:
    return function_name.replace(_SEP, ".")


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        self.tools[tool.definition.name] = tool

    def get(self, name: str) -> RegisteredTool | None:
        return self.tools.get(name) or self.tools.get(from_function_name(name))

    def names(self) -> list[str]:
        return list(self.tools)

    def specs(self, names: set[str] | None = None) -> list[dict]:
        """Function specs for the subset of tools a worker is allowed to see."""
        return [
            {
                "type": "function",
                "function": {
                    "name": to_function_name(t.definition.name),
                    "description": t.definition.description,
                    "parameters": t.definition.input_schema,
                },
            }
            for name, t in self.tools.items()
            if names is None or name in names
        ]
