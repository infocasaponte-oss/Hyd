# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Automatic distillation: expensive, verified HYDRA decisions become datasets for small
specialists (HYDRA-Router-1.5B, HYDRA-Critic-3B, HYDRA-Specialist-7B...).

HYDRA ensemble -> verified traces -> dataset -> LoRA/QLoRA student -> merge -> GGUF -> quantize
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from hydra.model_factory.runner import CommandResult, CommandRunner, ToolLocator, ToolMissing
from hydra.router.router import ROUTER_PROMPT
from hydra.telemetry.metrics import TaskRecord


class DatasetManifest(BaseModel):
    id: str = Field(default_factory=lambda: f"ds-{uuid.uuid4().hex[:8]}")
    kind: str  # routing | specialist | critic
    path: str
    examples: int
    filters: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TrainingJob(BaseModel):
    id: str = Field(default_factory=lambda: f"train-{uuid.uuid4().hex[:8]}")
    base_model: str
    dataset: str
    output_dir: str
    method: str = "lora"  # lora | qlora
    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    epochs: int = 2
    learning_rate: float = 2e-4
    max_seq_length: int = 2048
    batch_size: int = 4
    gradient_accumulation: int = 4
    target_modules: list[str] = Field(default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"])


def _ok(task: TaskRecord, min_confidence: float) -> bool:
    fr = task.final_response or {}
    meta = fr.get("meta") or {}
    return (task.status == "completed" and meta.get("decision", "answer") == "answer"
            and meta.get("confidence", 0) >= min_confidence and meta.get("verified") is True)


class DatasetBuilder:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, kind: str, rows: list[dict], filters: dict) -> DatasetManifest:
        m = DatasetManifest(kind=kind, path="", examples=len(rows), filters=filters)
        path = self.out_dir / f"{m.id}-{kind}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        m.path = str(path)
        (self.out_dir / f"{m.id}.json").write_text(m.model_dump_json(indent=1), encoding="utf-8")
        return m

    def routing(self, tasks: list[TaskRecord], min_confidence: float = 0.8) -> DatasetManifest:
        """request -> routing decision (the gold labels come from verified, confident runs)."""
        rows = []
        for t in tasks:
            if not t.route or not _ok(t, min_confidence):
                continue
            user = next((m["content"] for m in reversed(t.request.get("messages", [])) if m.get("role") == "user"), "")
            label = {k: t.route[k] for k in ("task_type", "complexity", "risk", "requires_tools", "requires_vision",
                                             "requires_reasoning", "requires_verification", "requires_memory")
                     if k in t.route}
            rows.append({"messages": [{"role": "system", "content": ROUTER_PROMPT},
                                      {"role": "user", "content": user[:4000]},
                                      {"role": "assistant", "content": json.dumps(label)}]})
        return self._write("routing", rows, {"min_confidence": min_confidence})

    def specialist(self, tasks: list[TaskRecord], task_type: str | None = None, min_confidence: float = 0.85,
                   tools: list[str] | None = None) -> DatasetManifest:
        """messages -> final verified answer: compiles a whole HYDRA workflow into one model call."""
        rows = []
        for t in tasks:
            if not _ok(t, min_confidence):
                continue
            meta = (t.final_response or {}).get("meta", {})
            if task_type and meta.get("task_type") != task_type:
                continue
            if tools is not None and sorted(meta.get("tools_used", [])) != sorted(tools):
                continue
            msgs = [{"role": m["role"], "content": m["content"]} for m in t.request.get("messages", [])]
            rows.append({"messages": msgs + [{"role": "assistant", "content": t.final_response["answer"]}]})
        return self._write("specialist", rows, {"task_type": task_type, "min_confidence": min_confidence,
                                                "tools": tools})

    def critic(self, tasks: list[TaskRecord]) -> DatasetManifest:
        """Export verified positives; an unverified answer is not a verified negative."""
        rows = []
        for t in tasks:
            fr = t.final_response or {}
            meta = fr.get("meta", {})
            if (not fr.get("answer") or meta.get("decision", "answer") != "answer"
                    or t.status != "completed" or meta.get("verified") is not True):
                continue
            verdict = {"verdict": "pass",
                       "score": round(meta.get("confidence", 0.5), 3), "issues": fr.get("uncertainties", [])[:5]}
            user = next((m["content"] for m in reversed(t.request.get("messages", [])) if m.get("role") == "user"), "")
            rows.append({"messages": [
                {"role": "system", "content": "Review the answer critically. Return JSON verdict."},
                {"role": "user", "content": f"TASK:\n{user[:3000]}\n\nANSWER:\n{fr['answer'][:6000]}"},
                {"role": "assistant", "content": json.dumps(verdict, ensure_ascii=False)}]})
        return self._write("critic", rows, {})


class LoRATrainer:
    """Runs hydra.model_factory.train_lora (transformers + peft) as a separate process -
    training happens in the Lab/Factory, never inside inference."""

    def __init__(self, runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    def available(self) -> bool:
        return self.tools.python_module("transformers") and self.tools.python_module("peft") \
            and self.tools.python_module("torch")

    async def train(self, job: TrainingJob) -> CommandResult:
        if not self.available():
            raise ToolMissing("LoRA training needs torch, transformers and peft (pip install transformers peft)")
        cfg = Path(job.output_dir) / "training_job.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(job.model_dump_json(indent=1), encoding="utf-8")
        return await self.runner.run([self.tools.python(), "-m", "hydra.model_factory.train_lora", str(cfg)])

    async def merge(self, base_model: str, adapter_dir: str, output_dir: str) -> CommandResult:
        if not self.available():
            raise ToolMissing("merging LoRA adapters needs torch, transformers and peft")
        return await self.runner.run([self.tools.python(), "-m", "hydra.model_factory.train_lora", "--merge",
                                      base_model, adapter_dir, output_dir])
