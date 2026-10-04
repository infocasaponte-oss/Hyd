# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA command line.

  hydra ask "¿Cuánto es 17 × 23?" [--mode deep] [--image foto.png] [--approve git.apply_patch]
  hydra serve [--host 0.0.0.0 --port 8080]
  hydra models | hardware | failures
  hydra eval <model-id> [--suites coding reasoning] [--apply]
  hydra lab list | create NAME --set accept_confidence=0.8 | benchmark ID | shadow ID | promote ID | rollback ID
  hydra model import SOURCE --name LOGICAL      (path | ollama:qwen3:8b | hf:Qwen/Qwen2.5-0.5B-Instruct)
  hydra model inspect PATH | list | lineage ARTIFACT
  hydra model build LOGICAL [--target laptop | --quant Q4_K_M Q5_K_M] [--format mlx onnx awq fp8]
  hydra model evaluate ARTIFACT | benchmark VARIANT | validate VARIANT | canary VARIANT
  hydra model optimize LOGICAL [--hardware local|profile.yaml] [--quality-min 0.95]
  hydra model resolve LOGICAL [--quality 0.9 --max-memory 12 --local]
  hydra model distill routing|specialist|critic | jit
  hydra factory worker | submit KIND --param k=v | status
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import os
import sys
from pathlib import Path

import hydra
from hydra.cli_io import kv_pairs as _kv
from hydra.cli_io import print_json as _print


def _settings(args):
    if getattr(args, "offline", False):
        os.environ["HYDRA_OFFLINE"] = "true"
    if getattr(args, "sandbox", None):
        os.environ["HYDRA_SANDBOX_BACKEND"] = args.sandbox
    from hydra.core.config import Settings
    return Settings()


def _image(path: str) -> str:
    if path.startswith(("http://", "https://", "data:")):
        return path
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _source(spec: str):
    from hydra.model_factory.manifest import ModelSource, SourceType

    if spec.startswith("ollama:"):
        return ModelSource(source_type=SourceType.OLLAMA, location=spec[7:])
    if spec.startswith("hf:"):
        return ModelSource(source_type=SourceType.HUGGINGFACE, location=spec[3:])
    p = Path(spec).expanduser()
    if p.is_dir():
        kind = SourceType.LORA if (p / "adapter_config.json").exists() else SourceType.LOCAL_DIR
    elif p.suffix == ".gguf":
        kind = SourceType.GGUF_FILE
    elif p.suffix == ".safetensors":
        kind = SourceType.SAFETENSORS_FILE
    elif p.exists():
        kind = SourceType.CHECKPOINT
    else:
        return ModelSource(source_type=SourceType.HUGGINGFACE, location=spec)
    return ModelSource(source_type=kind, location=str(p.resolve()))


async def _with_runtime(args, fn):
    from hydra.core.bootstrap import build_runtime

    runtime = await build_runtime(_settings(args))
    try:
        return await fn(runtime)
    finally:
        await runtime.close()


# ------------------------------------------------------------------ commands
async def cmd_ask(args, runtime) -> int:
    from hydra.core.contracts import ExecutionMode, HydraRequest, Message
    from hydra.core.kernel import HydraTaskFailed

    req = HydraRequest(messages=[Message(role="user", content=args.prompt,
                                         images=[_image(i) for i in args.image or []])],
                       mode=ExecutionMode(args.mode), local_only=args.local_only,
                       approved_actions=args.approve or [])
    try:
        result = await runtime.lab.serve(req)
    except HydraTaskFailed as exc:
        print(f"HYDRA failed ({exc.kind}): {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print(result)
        return 0
    print(result.answer)
    m = result.meta
    print(f"\n— {m.task_type.value} · {m.mode.value} · {m.decision} · models={','.join(m.models_used) or '-'} · "
          f"tools={','.join(m.tools_used) or '-'} · verified={m.verified} · confidence={m.confidence:.2f} · "
          f"{'cached · ' if m.cached else ''}{m.sensitivity} · {m.latency_ms:.0f} ms", file=sys.stderr)
    for c in result.claims:
        if c.status != "supported":
            print(f"  ⚠ {c.status}: {c.text[:120]}", file=sys.stderr)
    for p in result.pending_confirmations:
        print(f"  ⏸ needs approval: {p['tool']} (re-run with --approve {p['tool']})", file=sys.stderr)
    return 0


async def cmd_models(args, runtime) -> int:
    for m in runtime.registry.all():
        print(json.dumps({"id": m.id, "provider": m.provider, "tier": m.tier, "local": m.local,
                          "enabled": m.enabled, "runtime_model": m.physical_name,
                          "available": runtime.registry.breaker.available(m.id)}))
    return 0


async def cmd_eval(args, runtime) -> int:
    from hydra.evals.engine import apply_to_registry, summary_table

    report = await runtime.evaluator.run_model(runtime.registry.get(args.model), args.suites)
    for row in summary_table(report):
        print(f"{row['suite']:<14} {row['score']:.3f}  {row['passed']:>5}  {row['latency_ms']:>8.0f} ms")
    print(f"{'overall':<14} {report.overall:.3f}")
    if args.verbose:
        for c in report.cases:
            print(f"  {'✔' if c.passed else '✘'} {c.id:<22} {c.detail[:100]}")
    if args.apply:
        apply_to_registry(report, runtime.registry)
        print("registry profile updated with measured scores", file=sys.stderr)
    return 0


async def cmd_lab(args, runtime) -> int:
    lab = runtime.lab
    match args.action:
        case "list":
            for e in lab.experiments.values():
                print(f"{e.id}  {e.status.value:<12} {e.kind:<8} {e.name}  {e.overrides}")
        case "create":
            _print(lab.create(args.target, args.kind, _kv(args.set)))
        case "benchmark":
            _print(await lab.run_benchmark(args.target))
        case "shadow":
            _print(lab.start_shadow(args.target))
        case "promote":
            _print(lab.promote(args.target))
        case "rollback":
            _print(lab.rollback(args.target))
    return 0


async def cmd_model(args, runtime) -> int:
    from hydra.model_factory.inspector import inspect
    from hydra.model_factory.service import _hw
    from hydra.model_factory.store import ResolveConstraints

    f = runtime.factory
    match args.action:
        case "import":
            _print(await f.import_model(_source(args.target), args.name or Path(args.target).stem))
        case "inspect":
            target = f.store.artifacts[args.target].path if args.target in f.store.artifacts else args.target
            _print(inspect(target))
        case "list":
            for logical in f.store.logical_models():
                print(logical)
                for a in f.store.artifacts_of(logical):
                    print(f"  {a.id}  {a.format.value:<11} {a.quantization or '':<8} {a.size_bytes / 1e9:6.2f} GB  "
                          f"{a.path}")
                for v in f.store.variants_of(logical):
                    print(f"  ↳ {v.id}  {v.status}  approved={v.approved} q={v.quality_score:.3f} "
                          f"{v.tokens_per_second:.1f} tok/s {v.memory_gb:.1f} GB")
        case "lineage":
            _print([lin.model_dump(mode="json") for lin in f.store.ancestry(args.target)])
        case "build":
            _print(await f.build(args.target, args.build_target, _hw(args.hardware), args.quant, args.format))
        case "evaluate":
            _print(await f.evaluate_artifact(args.target, args.reference, args.endpoint, args.suites))
        case "benchmark":
            _print(await f.benchmark(args.target))
        case "validate":
            _print(await f.validate(args.target, args.reference, args.suites))
        case "canary":
            _print(await f.canary(args.target))
        case "optimize":
            _print(await f.optimize(args.target, _hw(args.hardware or "local"), args.quality_min,
                                    args.build_target, args.suites))
        case "resolve":
            _print(f.resolve(args.target, ResolveConstraints(quality=args.quality, max_memory_gb=args.max_memory,
                                                             local=args.local or None,
                                                             hardware=_hw(args.hardware))))
        case "distill":
            _print(await f.distill(args.target, **_kv(args.set)))
        case "jit":
            _print([p.model_dump() for p in await f.jit_proposals()])
    return 0


async def cmd_factory(args, runtime) -> int:
    f = runtime.factory
    match args.action:
        case "worker":
            print("HYDRA Model Factory worker running (Ctrl+C to stop)", file=sys.stderr)
            await f.run_worker(once=args.once)
        case "submit":
            _print(f.submit(args.kind, _kv(args.param)))
        case "status":
            _print(f.status())
    return 0


async def cmd_failures(args, runtime) -> int:
    _print(runtime.failures.report())
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The whole ``hydra`` command tree (engine and model factory); its shape is pinned by
    ``tests/contracts/cli.json``."""
    p = argparse.ArgumentParser(prog="hydra", description=f"HYDRA OS {hydra.__version__}. {hydra.__copyright__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--offline", action="store_true", help="deterministic offline models (no runtime)")
    common.add_argument("--sandbox", choices=["docker", "subprocess"])
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **kw: _add(*a, parents=[common], **kw)  # type: ignore[method-assign]

    ask = sub.add_parser("ask", help="run one request")
    ask.add_argument("prompt")
    ask.add_argument("--mode", default="balanced", choices=["fast", "balanced", "deep", "max", "private"])
    ask.add_argument("--local-only", action="store_true")
    ask.add_argument("--image", nargs="*", help="image paths or URLs")
    ask.add_argument("--approve", nargs="*", help="tools you approve for this request")
    ask.add_argument("--json", action="store_true")

    serve = sub.add_parser("serve", help="start the HTTP gateway")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    sub.add_parser("models", help="list the model registry")
    sub.add_parser("hardware", help="detect local hardware profile")
    sub.add_parser("failures", help="failure memory report")

    ev = sub.add_parser("eval", help="run HYDRA's eval suites on a model")
    ev.add_argument("model")
    ev.add_argument("--suites", nargs="*")
    ev.add_argument("--apply", action="store_true", help="write measured scores into the registry")
    ev.add_argument("-v", "--verbose", action="store_true")

    lab = sub.add_parser("lab", help="HYDRA Lab experiments")
    lab.add_argument("action", choices=["list", "create", "benchmark", "shadow", "promote", "rollback"])
    lab.add_argument("target", nargs="?")
    lab.add_argument("--kind", default="config")
    lab.add_argument("--set", nargs="*", help="override key=value (JSON values)")

    model = sub.add_parser("model", help="Model Factory")
    model.add_argument("action", choices=["import", "inspect", "list", "lineage", "build", "evaluate", "benchmark",
                                          "validate", "canary", "optimize", "resolve", "distill", "jit"])
    model.add_argument("target", nargs="?")
    model.add_argument("--name")
    model.add_argument("--target", dest="build_target", help="server_cpu | high_quality_local | laptop | edge")
    model.add_argument("--quant", nargs="*")
    model.add_argument("--format", nargs="*")
    model.add_argument("--hardware", help="'local' or a hardware profile YAML")
    model.add_argument("--quality-min", type=float, default=0.95)
    model.add_argument("--quality", type=float)
    model.add_argument("--max-memory", type=float)
    model.add_argument("--local", action="store_true")
    model.add_argument("--reference")
    model.add_argument("--endpoint")
    model.add_argument("--suites", nargs="*")
    model.add_argument("--set", nargs="*")

    fac = sub.add_parser("factory", help="Model Factory worker and jobs")
    fac.add_argument("action", choices=["worker", "submit", "status"])
    fac.add_argument("kind", nargs="?")
    fac.add_argument("--param", nargs="*")
    fac.add_argument("--once", action="store_true")

    from hydra.cli_platform import add_platform_parsers

    add_platform_parsers(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    from hydra.cli_platform import NO_RUNTIME, run_platform, run_without_runtime

    args = build_parser().parse_args(argv)
    if args.cmd in NO_RUNTIME:
        return run_without_runtime(args, _settings(args))
    if args.cmd == "serve":
        _settings(args)
        import uvicorn
        uvicorn.run("hydra.api.main:app", host=args.host, port=args.port)
        return 0
    if args.cmd == "hardware":
        from hydra.model_factory.hardware import detect_local, preferred_formats
        hw = detect_local()
        _print({**hw.model_dump(), "memory_budget_gb": round(hw.memory_budget_gb, 1),
                "preferred_formats": [f.value for f in preferred_formats(hw)]})
        return 0
    handlers = {"ask": cmd_ask, "models": cmd_models, "eval": cmd_eval, "lab": cmd_lab, "model": cmd_model,
                "factory": cmd_factory, "failures": cmd_failures}
    handler = handlers.get(args.cmd) or run_platform
    return asyncio.run(_with_runtime(args, lambda rt: handler(args, rt)))


if __name__ == "__main__":
    raise SystemExit(main())
