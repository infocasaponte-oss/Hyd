# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Calibration / imatrix builder: quantize with a dataset of HYDRA's *real* tasks
(coding, reasoning, tool calls, Spanish, English, long context, structured output)
instead of a generic corpus."""

from __future__ import annotations

from pathlib import Path

from hydra.evals.suites import builtin_suites
from hydra.model_factory.runner import CommandResult, CommandRunner, ToolLocator
from hydra.telemetry.metrics import TaskRecord

SEED_TEXTS = [
    "def merge_sorted(a, b):\n    i = j = 0\n    out = []\n    while i < len(a) and j < len(b):\n",
    "Explica paso a paso por qué la suma de dos números impares es siempre par.",
    "Prove that there are infinitely many prime numbers.",
    '{"tool_call": {"name": "python.execute", "arguments": {"code": "print(sum(i*i for i in range(101)))"}}}',
    "Resume en tres puntos las ventajas de usar PostgreSQL frente a SQLite en producción.",
    "The service listens on port 9123 and depends on Redis; the connection pool is exhausted under load.",
    '{"name": "Ana García", "age": 31, "city": "Vigo"}',
    "SELECT user_id, count(*) FROM orders WHERE created_at > now() - interval '7 days' GROUP BY 1;",
]


def build_calibration_text(tasks: list[TaskRecord] | None = None, max_chars: int = 400_000,
                           extra: list[str] | None = None) -> str:
    parts: list[str] = list(SEED_TEXTS)
    for suite in builtin_suites().values():
        parts += [c.prompt for c in suite]
    for t in tasks or []:
        msgs = t.request.get("messages", [])
        parts += [m.get("content", "") for m in msgs if m.get("content")]
        if t.final_response and (ans := t.final_response.get("answer")):
            parts.append(ans)
    parts += extra or []
    text = "\n\n".join(p for p in parts if p.strip())
    # long-context sample: repeat real content so the importance matrix sees long sequences
    if len(text) < max_chars // 4:
        text = text + "\n\n" + (text * 3)
    return text[:max_chars]


class ImatrixBuilder:
    def __init__(self, runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    def command(self, model: str, calibration_file: str, output: str, ctx: int = 512, chunks: int = 100) -> list[str]:
        return [self.tools.require_binary("llama-imatrix"), "-m", model, "-f", calibration_file, "-o", output,
                "-c", str(ctx), "--chunks", str(chunks)]

    async def build(self, model: str, calibration_text: str, out_dir: Path) -> tuple[Path, CommandResult]:
        out_dir.mkdir(parents=True, exist_ok=True)
        calib = out_dir / "calibration.txt"
        calib.write_text(calibration_text, encoding="utf-8")
        out = out_dir / "imatrix.dat"
        res = await self.runner.run(self.command(model, str(calib), str(out)))
        return out, res
