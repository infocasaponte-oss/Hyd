# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Selection of the source files given to the model for a change."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_BLOCKED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
}
_BLOCKED_PARTS = {".git", ".venv", "node_modules", "runtime", "__pycache__"}


@dataclass(frozen=True)
class ContextFile:
    path: str
    text: str


class CodeContextSelector:
    def __init__(
        self,
        *,
        max_files: int = 8,
        max_file_bytes: int = 64 * 1024,
        max_chars: int = 24_000,
    ):
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_chars = max_chars

    def select(self, workspace: str | Path, pytest_output: str) -> list[ContextFile]:
        root = Path(workspace).resolve()
        candidates: list[Path] = []
        seen: set[Path] = set()

        for token in pytest_output.split():
            cleaned = token.strip("()[]{}<>,;'\"")
            marker = cleaned.find(".py")
            if marker < 0:
                continue
            raw = cleaned[: marker + 3].replace("\\", "/")
            path = (root / raw).resolve()
            if self._eligible(root, path) and path not in seen:
                candidates.append(path)
                seen.add(path)

        if not candidates:
            for path in sorted(root.rglob("*.py")):
                resolved = path.resolve()
                if self._eligible(root, resolved) and resolved not in seen:
                    candidates.append(resolved)
                    seen.add(resolved)
                    if len(candidates) >= self.max_files:
                        break

        selected: list[ContextFile] = []
        remaining = self.max_chars
        for path in candidates:
            if len(selected) >= self.max_files or remaining <= 0:
                break
            size = path.stat().st_size
            if size > self.max_file_bytes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if len(text) > remaining:
                text = text[:remaining]
            if not text:
                continue
            selected.append(
                ContextFile(
                    path=str(path.relative_to(root)),
                    text=text,
                )
            )
            remaining -= len(text)

        return selected

    def render(self, files: list[ContextFile]) -> str:
        if not files:
            return "(no bounded source context selected)"
        chunks = []
        for item in files:
            chunks.append(f"FILE: {item.path}\n{item.text}")
        return "\n\n".join(chunks)

    @staticmethod
    def _eligible(root: Path, path: Path) -> bool:
        if path == root or root not in path.parents:
            return False
        if path.name in _BLOCKED_NAMES:
            return False
        relative = path.relative_to(root)
        if any(part in _BLOCKED_PARTS for part in relative.parts):
            return False
        return path.is_file() and not path.is_symlink()
