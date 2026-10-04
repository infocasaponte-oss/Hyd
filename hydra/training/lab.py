# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA Training Lab: production traces -> data vault -> datasets -> SFT/LoRA/QLoRA/DPO/MLX
-> evaluation -> quantization -> packaging -> candidate -> offline eval -> shadow -> canary.

Nothing trained ever enters production directly (Observe -> Propose -> Train -> Prove -> Deploy,
never Think -> Rewrite itself)."""

from __future__ import annotations

import json
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, Field

from hydra.core.hashing import hash_obj, now_iso
from hydra.model_factory.runner import CommandRunner, ToolLocator, ToolMissing


# ------------------------------------------------------------------------------ traces
class CognitiveTrace(BaseModel):
    task_id: str
    task_type: str
    input: dict[str, Any]
    route: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    model_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    verified_facts: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str = ""
    verifier_score: float = 0.0
    user_score: float | None = None
    cost: float = 0.0
    latency_ms: float = 0.0
    policy_violation: bool = False
    tool_failure: bool = False
    contaminated: bool = False


def trace_eligible(t: CognitiveTrace, min_verified: float = 0.9) -> tuple[bool, str]:
    """verified > .90 AND no policy violation AND no tool failure AND valid answer AND not contaminated."""
    if t.verifier_score <= min_verified:
        return False, "verification"
    if t.policy_violation:
        return False, "policy"
    if t.tool_failure:
        return False, "tool_failure"
    if not t.final_answer.strip():
        return False, "empty_answer"
    if t.contaminated:
        return False, "contamination"
    return True, "ok"


def traces_from_tasks(tasks: list, flight_dir: Path | None = None) -> list[CognitiveTrace]:
    out = []
    for t in tasks:
        fr = t.final_response or {}
        meta = fr.get("meta") or {}
        if not fr:
            continue
        req = t.request or {}
        msgs = req.get("messages") or [{}]
        flight = {}
        if flight_dir is not None and (flight_dir / f"{t.id}.json").exists():
            flight = json.loads((flight_dir / f"{t.id}.json").read_text(encoding="utf-8"))
        out.append(CognitiveTrace(
            task_id=str(t.id), task_type=meta.get("task_type", "chat"), input={"prompt": msgs[-1].get("content", "")},
            route=t.route or {}, model_calls=[{"model": m} for m in meta.get("models_used", [])],
            tool_calls=[{"tool": x} for x in meta.get("tools_used", [])],
            final_answer=fr.get("answer", ""), verifier_score=float(meta.get("confidence", 0.0)) if meta.get("verified")
            else float(meta.get("confidence", 0.0)) * 0.8, user_score=t.feedback if hasattr(t, "feedback") else None,
            latency_ms=float(meta.get("latency_ms", 0.0)), cost=float((fr.get("learning") or {}).get("cost", 0.0)),
            policy_violation=meta.get("decision") == "refuse",
            tool_failure=any(e.get("type") == "tool.failed" for e in flight.get("events", []))))
    return out


# ------------------------------------------------------------------------------ recipes / runs
class TrainingRecipe(BaseModel):
    name: str
    base_model: str
    method: str = "lora"  # sft | lora | qlora | dora | dpo | full | mlx-lora | classifier
    learning_rate: float = 1e-4
    epochs: float = 2
    lora_rank: int | None = 32
    lora_alpha: int | None = 64
    lora_dropout: float = 0.05
    max_length: int = 2048
    batch_size: int = 4
    gradient_accumulation: int = 4
    dataset_id: str
    backend: str = "auto"  # auto | trl | peft | mlx | builtin
    target_capability: str | None = None
    seed: int = 42

    @classmethod
    def from_yaml(cls, path: str | Path) -> TrainingRecipe:
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        lora = d.pop("lora", {}) or {}
        ds = d.pop("dataset", {}) or {}
        return cls(**d, lora_rank=lora.get("rank", d.get("lora_rank", 32)),
                   lora_alpha=lora.get("alpha", d.get("lora_alpha", 64)),
                   dataset_id=ds.get("id", d.get("dataset_id", "")) if isinstance(ds, dict) else ds)


class RunStatus(str, Enum):
    CREATED = "CREATED"
    DATASET_BUILDING = "DATASET_BUILDING"
    TRAINING = "TRAINING"
    EVALUATING = "EVALUATING"
    PACKAGING = "PACKAGING"
    READY = "READY"
    REJECTED = "REJECTED"


class TrainingRun(BaseModel):
    id: str = Field(default_factory=lambda: f"tr-{uuid4().hex[:8]}")
    recipe: TrainingRecipe
    dataset_release: str
    status: RunStatus = RunStatus.CREATED
    backend: str = ""
    hardware_profile: str = ""
    code_commit: str | None = None
    output_dir: str = ""
    output_artifacts: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    created_at: str = Field(default_factory=now_iso)

    def to(self, st: RunStatus, **info) -> None:
        self.status = st
        self.history.append({"status": st.value, "at": now_iso(), **info})


TRL_SFT_SCRIPT = r'''
import json, sys
from datasets import load_dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer
cfg = json.load(open(sys.argv[1]))
ds = load_dataset("json", data_files={"train": cfg["train"], "validation": cfg.get("validation") or cfg["train"]})
peft = None if cfg["method"] in ("sft", "full") else LoraConfig(r=cfg["lora_rank"], lora_alpha=cfg["lora_alpha"],
    lora_dropout=cfg["lora_dropout"], task_type="CAUSAL_LM", use_dora=cfg["method"] == "dora")
args = SFTConfig(output_dir=cfg["output_dir"], learning_rate=cfg["learning_rate"], num_train_epochs=cfg["epochs"],
                 per_device_train_batch_size=cfg["batch_size"], gradient_accumulation_steps=cfg["gradient_accumulation"],
                 max_length=cfg["max_length"], seed=cfg["seed"], logging_steps=10, save_strategy="epoch", report_to=[])
trainer = SFTTrainer(model=cfg["base_model"], train_dataset=ds["train"], eval_dataset=ds["validation"],
                     peft_config=peft, args=args)
trainer.train()
trainer.save_model(cfg["output_dir"])
print(json.dumps({"train_loss": trainer.state.log_history[-1].get("train_loss")}))
'''

TRL_DPO_SCRIPT = r'''
import json, sys
from datasets import load_dataset
from peft import LoraConfig
from trl import DPOConfig, DPOTrainer
cfg = json.load(open(sys.argv[1]))
ds = load_dataset("json", data_files={"train": cfg["train"]})
peft = LoraConfig(r=cfg["lora_rank"], lora_alpha=cfg["lora_alpha"], task_type="CAUSAL_LM")
args = DPOConfig(output_dir=cfg["output_dir"], learning_rate=cfg["learning_rate"], num_train_epochs=cfg["epochs"],
                 per_device_train_batch_size=cfg["batch_size"], seed=cfg["seed"], report_to=[])
trainer = DPOTrainer(model=cfg["base_model"], train_dataset=ds["train"], peft_config=peft, args=args)
trainer.train(); trainer.save_model(cfg["output_dir"])
'''


class TrainingBackends:
    """PyTorch/CUDA (TRL SFT/DPO, PEFT LoRA/QLoRA/DoRA), Apple Silicon (mlx-lm LoRA/QLoRA/DoRA),
    and a builtin CPU backend for small classifier specialists (routers/critics heads)."""

    def __init__(self, runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    @staticmethod
    def _has(mod: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(mod) is not None

    def available(self) -> dict[str, bool]:
        return {"trl": self._has("trl") and self._has("peft") and self._has("torch"),
                "peft": self._has("peft") and self._has("transformers") and self._has("torch"),
                "mlx": self._has("mlx_lm"), "builtin": True}

    def choose(self, recipe: TrainingRecipe) -> str:
        if recipe.method == "classifier":
            return "builtin"
        if recipe.method == "qlora" and recipe.backend in ("auto", "trl"):
            if self._has("peft") and self._has("transformers") and self._has("bitsandbytes"):
                return "peft"
            raise ToolMissing("QLoRA requires peft, transformers and bitsandbytes")
        if recipe.backend != "auto":
            return recipe.backend
        av = self.available()
        if recipe.method.startswith("mlx") or (sys.platform == "darwin" and av["mlx"]):
            return "mlx"
        if av["trl"]:
            return "trl"
        if av["peft"]:
            return "peft"
        raise ToolMissing("no training backend: install hydra-engine[training] (torch, transformers, peft, trl) "
                          "or mlx-lm on Apple Silicon")

    async def train(self, run: TrainingRun, train_file: Path, valid_file: Path | None, work: Path) -> dict[str, Any]:
        r = run.recipe
        backend = self.choose(r)
        run.backend = backend
        cfg = {**r.model_dump(), "train": str(train_file), "validation": str(valid_file) if valid_file else None,
               "output_dir": str(work / "adapter")}
        (work / "job.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        if backend == "builtin":
            from hydra.training.specialists import train_text_classifier

            return train_text_classifier(train_file, valid_file, work / "adapter", seed=r.seed)
        if backend == "mlx":
            data_dir = work / "mlx-data"
            data_dir.mkdir(exist_ok=True)
            (data_dir / "train.jsonl").write_bytes(train_file.read_bytes())
            (data_dir / "valid.jsonl").write_bytes((valid_file or train_file).read_bytes())
            cmd = [sys.executable, "-m", "mlx_lm.lora", "--model", r.base_model, "--train", "--data", str(data_dir),
                   "--adapter-path", cfg["output_dir"], "--iters", str(int(max(1, r.epochs) * 100)),
                   "--learning-rate", str(r.learning_rate)]
            if r.method in ("qlora", "mlx-qlora"):
                cmd += ["--fine-tune-type", "lora"]
            res = await self.runner.run(cmd, timeout=24 * 3600)
        else:
            script = work / ("dpo.py" if r.method == "dpo" else "sft.py")
            script.write_text(TRL_DPO_SCRIPT if r.method == "dpo" else TRL_SFT_SCRIPT, encoding="utf-8")
            if backend == "peft":
                cmd = [sys.executable, "-m", "hydra.model_factory.train_lora", str(work / "job.json")]
            else:
                cmd = [sys.executable, str(script), str(work / "job.json")]
            res = await self.runner.run(cmd, timeout=24 * 3600)
        if res.returncode != 0:
            raise RuntimeError(f"training failed ({backend}): {res.stderr[-1500:]}")
        return {"backend": backend, "stdout_tail": res.stdout[-800:]}


# ------------------------------------------------------------------------------ reward
class RewardEngine:
    """Objective rewards: Reward = Q - λ·C - μ·L (not only 'I liked this answer')."""

    CODE = {"unit_tests": 0.40, "static_checks": 0.15, "correct_output": 0.25, "efficiency": 0.10, "critic": 0.10}
    ROUTING = {"correct_specialist": 0.40, "quality_achieved": 0.30, "latency": 0.15, "cost": 0.15}

    @staticmethod
    def weighted(weights: dict[str, float], signals: dict[str, float]) -> float:
        return round(sum(w * float(signals.get(k, 0.0)) for k, w in weights.items()), 4)

    def code(self, **signals: float) -> float:
        return self.weighted(self.CODE, signals)

    def routing(self, **signals: float) -> float:
        return self.weighted(self.ROUTING, signals)

    @staticmethod
    def utility(quality: float, cost: float, latency_s: float, lam: float = 0.5, mu: float = 0.02) -> float:
        return round(quality - lam * cost - mu * latency_s, 4)


# ------------------------------------------------------------------------------ discovery / ROI
class TaskCluster(BaseModel):
    id: str
    label: str
    volume: int
    share: float
    task_types: dict[str, int]
    tools: dict[str, int]
    mean_confidence: float
    mean_cost: float
    mean_calls: float
    examples: list[str] = Field(default_factory=list)
    specialist_exists: bool = False


class SpecialistProposal(BaseModel):
    name: str
    cluster_id: str
    suggested_size: str
    volume_per_month: float
    current_cost_month: float
    estimated_specialist_cost_month: float
    training_cost: float
    roi: float
    expected_savings: float
    status: str = "PROPOSED"


class SpecialistDiscovery:
    """Cluster traces (hashed bag-of-words + k-means) -> frequent families -> ROI-gated proposals."""

    def __init__(self, k: int = 8, dims: int = 256, seed: int = 0) -> None:
        self.k, self.dims, self.seed = k, dims, seed

    def _vec(self, text: str):
        import numpy as np

        v = np.zeros(self.dims)
        for tok in text.lower().split():
            v[hash(tok) % self.dims] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def clusters(self, traces: list[CognitiveTrace]) -> list[TaskCluster]:
        import numpy as np

        if not traces:
            return []
        X = np.stack([self._vec(f"{t.task_type} {t.input.get('prompt', '')} "
                                f"{' '.join(c.get('tool', '') for c in t.tool_calls)}") for t in traces])
        k = min(self.k, len(traces))
        rng = np.random.default_rng(self.seed)
        C = X[rng.choice(len(X), k, replace=False)]
        for _ in range(25):
            labels = np.argmax(X @ C.T, axis=1)
            newC = np.stack([X[labels == i].mean(0) if (labels == i).any() else C[i] for i in range(k)])
            if np.allclose(newC, C):
                break
            C = newC
        out = []
        for i in range(k):
            idx = [j for j in range(len(traces)) if labels[j] == i]
            if not idx:
                continue
            ts = [traces[j] for j in idx]
            tt: dict[str, int] = {}
            tools: dict[str, int] = {}
            for t in ts:
                tt[t.task_type] = tt.get(t.task_type, 0) + 1
                for c in t.tool_calls:
                    tools[c.get("tool", "?")] = tools.get(c.get("tool", "?"), 0) + 1
            label = max(tt, key=tt.get) + ("+" + max(tools, key=tools.get) if tools else "")
            out.append(TaskCluster(id=f"cl-{i}", label=label, volume=len(ts), share=round(len(ts) / len(traces), 3),
                                   task_types=tt, tools=tools,
                                   mean_confidence=round(sum(t.verifier_score for t in ts) / len(ts), 3),
                                   mean_cost=round(sum(t.cost for t in ts) / len(ts), 6),
                                   mean_calls=round(sum(len(t.model_calls) for t in ts) / len(ts), 2),
                                   examples=[t.input.get("prompt", "")[:120] for t in ts[:3]]))
        return sorted(out, key=lambda c: -c.volume)

    @staticmethod
    def roi(current_cost_month: float, specialist_cost_month: float, training_cost: float) -> float:
        """ROI = (CurrentCost - EstimatedSpecialistCost) / TrainingCost (monthly)."""
        return round((current_cost_month - specialist_cost_month) / max(training_cost, 1e-9), 3)

    def propose(self, clusters: list[TaskCluster], *, window_days: float = 30, min_volume_month: float = 1000,
                min_roi: float = 1.0, training_cost: float = 2500, cost_per_call: float = 0.002,
                specialist_cost_ratio: float = 0.14) -> list[SpecialistProposal]:
        out = []
        for c in clusters:
            if c.specialist_exists:
                continue
            per_month = c.volume * 30 / max(window_days, 1e-9)
            if per_month < min_volume_month:
                continue
            cur = per_month * max(c.mean_cost, c.mean_calls * cost_per_call)
            spec = cur * specialist_cost_ratio
            r = self.roi(cur, spec, training_cost)
            if r < min_roi:
                continue
            size = "0.6-1B" if c.label.startswith(("chat", "tool_use")) or "routing" in c.label else \
                "1.5-3B" if c.mean_calls < 3 else "3-7B"
            out.append(SpecialistProposal(name=f"HYDRA-{c.label.replace('+', '-').replace('.', '-')}-{size}",
                                          cluster_id=c.id, suggested_size=size, volume_per_month=round(per_month),
                                          current_cost_month=round(cur, 2), estimated_specialist_cost_month=round(spec, 2),
                                          training_cost=training_cost, roi=r,
                                          expected_savings=round(1 - specialist_cost_ratio, 3)))
        return sorted(out, key=lambda p: -p.roi)


# ------------------------------------------------------------------------------ arena / gates
class ArenaResult(BaseModel):
    candidate: str
    baseline: str
    overall: dict[str, float]
    slices: dict[str, dict[str, float]]
    metrics: dict[str, Any] = Field(default_factory=dict)
    regressions: list[dict[str, Any]] = Field(default_factory=list)
    passed: bool = False
    reasons: list[str] = Field(default_factory=list)


class RegressionGuard(BaseModel):
    allowed_slice_drop: float = 0.03
    allowed_latency_increase: float = 0.25
    require_overall_improvement: bool = False

    def check(self, cand: dict[str, float], base: dict[str, float], slices_c: dict[str, float],
              slices_b: dict[str, float], lat_c: float | None = None, lat_b: float | None = None
              ) -> tuple[bool, list[dict], list[str]]:
        regs, reasons = [], []
        oc, ob = cand.get("overall", 0), base.get("overall", 0)
        if oc < ob - 1e-9 or (self.require_overall_improvement and oc <= ob):
            reasons.append(f"overall {oc:.3f} < baseline {ob:.3f}")
        for s, vb in slices_b.items():
            vc = slices_c.get(s, 0.0)
            if vb - vc > self.allowed_slice_drop:
                regs.append({"slice": s, "baseline": vb, "candidate": vc, "drop": round(vb - vc, 4)})
        if regs:
            reasons.append(f"{len(regs)} slice regressions > {self.allowed_slice_drop:.0%}")
        if lat_c and lat_b and lat_c > lat_b * (1 + self.allowed_latency_increase):
            reasons.append(f"latency {lat_c:.0f}ms > {lat_b:.0f}ms +{self.allowed_latency_increase:.0%}")
        return not reasons, regs, reasons


class EvalArena:
    """Candidate vs production vs previous candidate: quality per slice, latency, memory, tools, JSON..."""

    def __init__(self, evaluator=None, guard: RegressionGuard | None = None) -> None:
        self.evaluator = evaluator
        self.guard = guard or RegressionGuard()

    @staticmethod
    def summarize(report) -> tuple[dict[str, float], dict[str, float], float | None]:
        slices = {name: s.score for name, s in report.suites.items()}
        lats = [c.latency_ms for c in report.cases if c.latency_ms > 0]
        return {"overall": report.overall}, slices, (sum(lats) / len(lats) if lats else None)

    def compare(self, cand_report, base_report) -> ArenaResult:
        oc, sc, lc = self.summarize(cand_report)
        ob, sb, lb = self.summarize(base_report)
        ok, regs, reasons = self.guard.check(oc, ob, sc, sb, lc, lb)
        if not cand_report.cases or not base_report.cases or not sc or not sb:
            ok = False
            reasons.append("missing evaluation evidence")
        if set(sc) != set(sb):
            ok = False
            reasons.append("candidate and baseline suites differ")
        return ArenaResult(candidate=cand_report.target, baseline=base_report.target, overall={**oc, "baseline": ob["overall"]},
                           slices={"candidate": sc, "baseline": sb},
                           metrics={"latency_ms": lc, "baseline_latency_ms": lb}, regressions=regs, passed=ok,
                           reasons=reasons)

    async def run(self, candidate, baseline, suites: list[str] | None = None) -> ArenaResult:
        cr = await self.evaluator.run_model(candidate, suites)
        br = await self.evaluator.run_model(baseline, suites)
        return self.compare(cr, br)


class PromotionGate(BaseModel):
    offline_eval_passed: bool = False
    shadow_passed: bool = False
    canary_passed: bool = False
    security_passed: bool = False
    artifact_signed: bool = False
    lineage_complete: bool = False

    @property
    def promotable(self) -> bool:
        return all(self.model_dump().values())

    def missing(self) -> list[str]:
        return [k for k, v in self.model_dump().items() if not v]


# ------------------------------------------------------------------------------ orchestrator
class TrainingOrchestrator:
    """SpecialistProposal -> dataset -> train -> checkpoint -> evaluate -> package -> candidate."""

    def __init__(self, runtime, backends: TrainingBackends | None = None) -> None:
        self.rt = runtime
        self.backends = backends or TrainingBackends()
        self.root = runtime.settings.data_dir / "training"
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_path = self.root / "runs.json"
        self.runs: dict[str, TrainingRun] = {}
        if self.runs_path.exists():
            for k, v in json.loads(self.runs_path.read_text(encoding="utf-8")).items():
                self.runs[k] = TrainingRun.model_validate(v)

    def _save(self) -> None:
        self.runs_path.write_text(json.dumps({k: v.model_dump(mode="json") for k, v in self.runs.items()}, indent=2),
                                  encoding="utf-8")

    def _ledger(self, et: str, run: TrainingRun, **payload) -> None:
        if getattr(self.rt, "ledger", None) is not None:
            self.rt.ledger.append(et, {"run": run.id, "recipe": run.recipe.name, "dataset": run.dataset_release,
                                       "status": run.status.value, **payload},
                                  object_type="training_run", object_id=run.id)

    async def run(self, recipe: TrainingRecipe, dataset_spec=None, eval_fn=None) -> TrainingRun:
        from hydra.corpus.factory import DatasetSpec

        run = TrainingRun(recipe=recipe, dataset_release=recipe.dataset_id)
        self.runs[run.id] = run
        work = self.root / run.id
        work.mkdir(parents=True, exist_ok=True)
        run.output_dir = str(work)
        try:
            run.to(RunStatus.DATASET_BUILDING)
            spec = dataset_spec or DatasetSpec(name=recipe.dataset_id or f"{recipe.name}-data",
                                               format="raw" if recipe.method == "classifier" else
                                               ("dpo" if recipe.method == "dpo" else "sft"))
            release = self.rt.datasets.build(spec)
            run.dataset_release = release.id
            files = {Path(n).stem: Path(release.path) / n for n in release.files}
            train, valid = files.get("train"), files.get("validation")
            if train is None or release.splits.get("train", 0) == 0:
                raise RuntimeError("empty training split")
            self._ledger("TRAINING_STARTED", run, examples=release.examples)
            run.to(RunStatus.TRAINING, backend=self.backends.choose(recipe))
            self._save()
            t0 = time.perf_counter()
            info = await self.backends.train(run, train, valid if valid and valid.stat().st_size else None, work)
            run.metrics.update(info)
            run.metrics["train_seconds"] = round(time.perf_counter() - t0, 2)
            for p in (work / "adapter").rglob("*") if (work / "adapter").exists() else []:
                if p.is_file():
                    m = self.rt.artifact_store.put_file(p, artifact_type="adapter" if recipe.method != "classifier"
                                                        else "classifier", task_id=run.id,
                                                        media_type="application/octet-stream")
                    run.output_artifacts.append(m.uri)
            self._ledger("TRAINING_COMPLETED", run, artifacts=run.output_artifacts)
            self.rt.corpus.add_lineage(f"dataset:{release.id}", f"training_run:{run.id}", "training")
            self.rt.corpus.add_lineage(f"training_run:{run.id}", f"model:{recipe.name}", "model")
            run.to(RunStatus.EVALUATING)
            if eval_fn is not None:
                run.metrics["eval"] = await eval_fn(run)
            elif "valid_accuracy" in run.metrics:
                run.metrics["eval"] = {"passed": run.metrics["valid_accuracy"] >= 0.7,
                                       "accuracy": run.metrics["valid_accuracy"]}
            evaluation = run.metrics.get("eval")
            passed = isinstance(evaluation, dict) and evaluation.get("passed") is True
            if not passed:
                run.error = "evaluation missing or did not explicitly pass"
            run.to(RunStatus.PACKAGING)
            manifest = {"run": run.id, "recipe": recipe.model_dump(), "dataset": release.id,
                        "artifacts": run.output_artifacts, "metrics": run.metrics,
                        "lineage_hash": hash_obj([release.record_ids_hash, recipe.model_dump()])}
            (work / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
            from hydra.training.signing import sign_directory

            sign_directory(work / "adapter" if (work / "adapter").exists() else work, self.rt.signer,
                           extra={"manifest": manifest})
            self._ledger("MODEL_TRAINED" if passed else "RELEASE_BLOCKED", run, passed=passed)
            run.to(RunStatus.READY if passed else RunStatus.REJECTED)
        except ToolMissing as exc:
            run.error = str(exc)
            run.to(RunStatus.REJECTED, reason="tool_missing")
        except Exception as exc:
            run.error = f"{type(exc).__name__}: {exc}"
            run.to(RunStatus.REJECTED, reason="error")
        self._save()
        return run


def meta_learning_dashboard(runs: list, registry) -> dict[str, Any]:
    """Share of work solved by small / medium / large / ensemble + specialists (how HYDRA specialises)."""
    by_task: dict[str, list] = {}
    for r in runs:
        by_task.setdefault(str(r.task_id), []).append(r)
    buckets = {"small": 0, "medium": 0, "large": 0, "ensemble": 0}
    for rs in by_task.values():
        gen = [r for r in rs if r.role in ("reasoner", "coder") and r.success]
        if not gen:
            continue
        if len({r.model_id for r in gen}) > 1:
            buckets["ensemble"] += 1
            continue
        m = registry.models.get(gen[0].model_id)
        tier = m.tier if m else 2
        buckets["small" if tier <= 1 else "medium" if tier <= 3 else "large"] += 1
    total = sum(buckets.values()) or 1
    lat = [r.latency_ms for r in runs if r.success]
    return {"tasks": len(by_task), "solved_by": {k: round(v / total, 3) for k, v in buckets.items()},
            "mean_latency_ms": round(sum(lat) / len(lat), 1) if lat else None,
            "specialists": [m.id for m in registry.all() if m.logical_model and m.logical_model.startswith("hydra-")]}
