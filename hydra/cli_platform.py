# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA 1.0 CLI commands.

  hydra run "..." [--mode deep]                 hydra task run task.yaml
  hydra goal "Encuentra y corrige el bug" --workspace ./repo [--approve node]
  hydra world stats|query Q|conflicts|codegraph PATH|at VERSION
  hydra corpus stats|search TEXT|export|snapshot|tombstone ID --reason R|synthetic --capability C --count N
  hydra dataset build RECIPE.yaml | list | verify RELEASE
  hydra train run RECIPE.yaml [--dataset SPEC.yaml] | specialists | dashboard
  hydra ip propose TITLE --feature F ... | list | status INV STATUS --actor A | effect INV --metric M ... | bundle INV
  hydra ledger verify|anchor|events [--object TYPE:ID]
  hydra license evaluate --target enterprise-commercial --component id=license ...
  hydra bom generate [--out DIR]          hydra release build NAME | verify PATH | promote PATH ENV
  hydra replay TASK [--mode audit|simulation] [--replace-model a=b]   hydra replay --traces 500 --config c.json
  hydra redteam | doctor | e2e [--limit N]      hydra discover MODEL [--apply]
  hydra build --auto [--model M] [--runtime ollama|llama.cpp] [--apply]
  hydra edge profile|scout|residency MODEL      hydra translate TEXT --to en [--glossary NAME] [--file F]
  hydra glossary set NAME k=v ... | show NAME   hydra mcp [--tools ...]   hydra mcp-client -- CMD ARGS
  hydra cluster nodes|place [--mode fast]       hydra worker --capability inference
  hydra flags list|set NAME VALUE               hydra config show|commit ENV k=v ...
  hydra backup OUT.tar.gz | restore ARCHIVE --data-dir DIR     hydra sync export OUT | import FILE
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from hydra.cli_io import kv_pairs as _kv
from hydra.cli_io import print_json as _print



def add_platform_parsers(sub) -> None:
    r = sub.add_parser("run", help="run a task through the kernel (alias of ask)")
    r.add_argument("prompt")
    r.add_argument("--mode", default="balanced", choices=["fast", "balanced", "deep", "max", "private"])
    r.add_argument("--json", action="store_true")

    t = sub.add_parser("task", help="run a HydraTask from YAML/JSON")
    t.add_argument("action", choices=["run"])
    t.add_argument("file")

    g = sub.add_parser("goal", help="Planner/Simulator: pursue a goal with objective success conditions")
    g.add_argument("goal")
    g.add_argument("--workspace")
    g.add_argument("--mode", default="balanced")
    g.add_argument("--approve", nargs="*", default=[])
    g.add_argument("--max-seconds", type=float, default=900)

    w = sub.add_parser("world", help="World Model + Belief Graph")
    w.add_argument("action", choices=["stats", "query", "conflicts", "codegraph", "at", "export"])
    w.add_argument("target", nargs="?")

    c = sub.add_parser("corpus", help="Corpus Engine")
    c.add_argument("action", choices=["stats", "search", "export", "snapshot", "tombstone", "synthetic", "prune"])
    c.add_argument("target", nargs="?")
    c.add_argument("--reason", default="")
    c.add_argument("--capability", default="reasoning.arithmetic")
    c.add_argument("--language")
    c.add_argument("--count", type=int, default=20)

    d = sub.add_parser("dataset", help="Dataset Factory")
    d.add_argument("action", choices=["build", "list", "verify"])
    d.add_argument("target", nargs="?")
    d.add_argument("--name")
    d.add_argument("--format", default="sft")
    d.add_argument("--record-types", nargs="*")

    tr = sub.add_parser("train", help="Training Lab")
    tr.add_argument("action", choices=["run", "specialists", "dashboard", "runs"])
    tr.add_argument("target", nargs="?")
    tr.add_argument("--dataset")

    ip = sub.add_parser("ip", help="IP ledger: inventions, effects, bundles")
    ip.add_argument("action", choices=["propose", "list", "status", "effect", "bundle", "timeline", "prior-art"])
    ip.add_argument("target", nargs="*")
    ip.add_argument("--problem", default="")
    ip.add_argument("--mechanism", default="")
    ip.add_argument("--solution", default="")
    ip.add_argument("--feature", nargs="*", default=[])
    ip.add_argument("--contributor", nargs="*", default=[])
    ip.add_argument("--actor", default="cli")
    ip.add_argument("--metric")
    ip.add_argument("--baseline", type=float)
    ip.add_argument("--value", type=float)
    ip.add_argument("--unit", default="")
    ip.add_argument("--higher-is-better", action="store_true")
    ip.add_argument("--reference", nargs="*", default=[])

    lg = sub.add_parser("ledger", help="provenance ledger")
    lg.add_argument("action", choices=["verify", "anchor", "events", "proof"])
    lg.add_argument("--object")
    lg.add_argument("--sequence", type=int)
    lg.add_argument("--limit", type=int, default=50)

    li = sub.add_parser("license", help="license compatibility engine")
    li.add_argument("action", choices=["evaluate", "packages"])
    li.add_argument("--target", default="enterprise-commercial")
    li.add_argument("--component", nargs="*", default=[])

    bm = sub.add_parser("bom", help="SBOM / ML-BOM / DBOM (CycloneDX)")
    bm.add_argument("action", choices=["generate"])
    bm.add_argument("--out", default="bom")
    bm.add_argument("--artifact", nargs="*", default=[])

    rl = sub.add_parser("release", help="signed releases")
    rl.add_argument("action", choices=["build", "verify", "promote", "gate"])
    rl.add_argument("target", nargs="*")

    rp = sub.add_parser("replay", help="replay a task (audit/simulation/counterfactual) or historical traces")
    rp.add_argument("task", nargs="?")
    rp.add_argument("--mode", default="audit", choices=["audit", "simulation"])
    rp.add_argument("--replace-model", nargs="*", default=[])
    rp.add_argument("--traces", type=int)
    rp.add_argument("--config")

    sub.add_parser("redteam", help="run the red team / chaos suite")
    doc = sub.add_parser("doctor", help="System Contract invariants + HYDRA 1.0 Definition of Done")
    doc.add_argument("--no-recovery", action="store_true")
    e2e = sub.add_parser("e2e", help="HYDRA-E2E-100 benchmark")
    e2e.add_argument("--limit", type=int)
    e2e.add_argument("--category", nargs="*")

    ds = sub.add_parser("discover", help="Capability Discovery Engine for a model")
    ds.add_argument("model")
    ds.add_argument("--apply", action="store_true")

    b = sub.add_parser("build", help="AutoBuilder: best runtime config for this machine")
    b.add_argument("--auto", action="store_true", required=True)
    b.add_argument("--model")
    b.add_argument("--runtime", default="ollama", choices=["ollama", "llama.cpp"])
    b.add_argument("--llama-server")
    b.add_argument("--apply", action="store_true", help="write the winner to .env")
    b.add_argument("--output", default="runtime/runtime-manifest.json")

    ed = sub.add_parser("edge", help="edge / workstation engine")
    ed.add_argument("action", choices=["profile", "scout", "residency", "pin-cpu"])
    ed.add_argument("target", nargs="?")
    ed.add_argument("--dirs", nargs="*", default=["models"])
    ed.add_argument("--gpu", help="profile this GPU instead of detecting the local one")
    ed.add_argument("--vram-mb", type=int, help="VRAM of --gpu in MB")
    pf = sub.add_parser("profile", help="hardware profile (HYDRA-SO alias of 'edge profile')")
    pf.add_argument("--gpu")
    pf.add_argument("--vram-mb", type=int)

    tl = sub.add_parser("translate", help="Translation Engine (language.translate)")
    tl.add_argument("text", nargs="?")
    tl.add_argument("--to", required=True)
    tl.add_argument("--source")
    tl.add_argument("--glossary")
    tl.add_argument("--domain", default="general")
    tl.add_argument("--file")
    tl.add_argument("--model")

    gl = sub.add_parser("glossary", help="persistent translation glossaries")
    gl.add_argument("action", choices=["set", "show", "list"])
    gl.add_argument("name", nargs="?")
    gl.add_argument("terms", nargs="*")

    mc = sub.add_parser("mcp", help="serve HYDRA as an MCP server over stdio")
    mc.add_argument("--tools", nargs="*")
    mcc = sub.add_parser("mcp-client", help="list the tools of an external MCP server (stdio)")
    mcc.add_argument("command", nargs=argparse_remainder())

    cl = sub.add_parser("cluster", help="cluster nodes and placement")
    cl.add_argument("action", choices=["nodes", "place"])
    cl.add_argument("--mode", default="balanced")
    cl.add_argument("--task-type", default="chat")

    wk = sub.add_parser("worker", help="execution-fabric worker (consumes WorkItems)")
    wk.add_argument("--capability", nargs="*", default=["inference"])
    wk.add_argument("--once", action="store_true")

    fl = sub.add_parser("flags", help="feature flags")
    fl.add_argument("action", choices=["list", "set"])
    fl.add_argument("name", nargs="?")
    fl.add_argument("value", nargs="?")

    cf = sub.add_parser("config", help="versioned configuration registry")
    cf.add_argument("action", choices=["show", "commit", "history", "rollback"])
    cf.add_argument("env", nargs="?", default="production")
    cf.add_argument("values", nargs="*")
    cf.add_argument("--version", type=int)

    ks = sub.add_parser("keys", help="private keys: export them as files for a mounted secret")
    ks.add_argument("action", choices=["export"])
    ks.add_argument("--out", required=True, help="directory for <name>.key files (keep it private)")

    bk = sub.add_parser("backup", help="coherent backup of the data plane")
    bk.add_argument("out")
    bk.add_argument("--include-private-keys", action="store_true")
    rs = sub.add_parser("restore", help="restore + verify a backup")
    rs.add_argument("archive")
    rs.add_argument("--data-dir", required=True)
    rs.add_argument("--overwrite", action="store_true")

    sy = sub.add_parser("sync", help="edge <-> central signed delta sync")
    sy.add_argument("action", choices=["export", "import"])
    sy.add_argument("file")
    sy.add_argument("--origin", default="")
    sy.add_argument("--world-version", type=int, default=0)
    sy.add_argument("--corpus-offset", type=int, default=0)
    sy.add_argument("--trust-key", action="append", default=[], metavar="PUB_PEM",
                    help="extra public key file trusted for this import (operator decision; "
                         "the node key and <data_dir>/keys/trusted/*.pub.pem are always trusted)")


def argparse_remainder():
    import argparse

    return argparse.REMAINDER


NO_RUNTIME = {"backup", "restore", "build", "edge", "profile", "release_verify", "keys"}


async def run_platform(args, rt) -> int:  # noqa: C901 - command table
    cmd = args.cmd
    if cmd == "run":
        from hydra.core.contracts import ExecutionMode, HydraRequest, Message

        r = await rt.lab.serve(HydraRequest(messages=[Message(role="user", content=args.prompt)],
                                            mode=ExecutionMode(args.mode)))
        if args.json:
            _print(r)
        else:
            print(r.answer)
            print(f"\n— confidence={r.meta.confidence:.2f} verified={r.meta.verified} "
                  f"learning={json.dumps({k: v for k, v in r.learning.items() if k in ('world_version', 'corpus')}, default=str)}",
                  file=sys.stderr)
        return 0
    if cmd == "task":
        import yaml

        from hydra.core.task import HydraResult, HydraTask

        data = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
        task = HydraTask.model_validate(data)
        _print(HydraResult.from_response(await rt.lab.serve(task.to_request(), task_id=task.id)))
        return 0
    if cmd == "goal":
        res = await rt.goals.run(args.goal, workspace=Path(args.workspace) if args.workspace else None,
                                 mode=args.mode, authorized=set(args.approve), max_seconds=args.max_seconds)
        for s in res.steps:
            print(f"  {'✔' if s.success else '✘'} {s.action:<18} {s.summary[:90]}  ({s.duration_ms:.0f} ms)")
        print(f"status={res.status} replans={res.replans} plans={res.selected_plans} system={res.system}")
        if res.patch:
            print(res.patch)
        if res.answer and not res.patch:
            print(res.answer)
        return 0 if res.status == "achieved" else 2
    if cmd == "world":
        w = rt.world
        match args.action:
            case "stats":
                _print(w.stats())
            case "query":
                print(rt.world_rag.packet(args.target or "").render() or "(nothing)")
            case "conflicts":
                _print([[b.model_dump() for b in grp] for grp in w.conflicts()])
            case "codegraph":
                from hydra.world.knowledge import code_graph_delta

                dl = code_graph_delta(Path(args.target), w)
                print(f"world v{w.apply(dl)}: +{len(dl.entities_created)} entities +{len(dl.relations_added)} relations")
            case "at":
                _print(w.at_version(int(args.target)).stats())
            case "export":
                _print(w.export())
        return 0
    if cmd == "corpus":
        from hydra.corpus.analytics import CorpusAnalytics

        c = rt.corpus
        match args.action:
            case "stats":
                _print(CorpusAnalytics(c).health())
            case "search":
                for r in c.search(text=args.target, limit=20):
                    print(f"{r.id}  {r.record_type.value:<18} {r.training_status.value:<11} q={r.quality:.2f} "
                          f"{json.dumps(r.input, ensure_ascii=False)[:90]}")
            case "export":
                _print(c.export_partitioned())
            case "snapshot":
                _print(c.snapshot())
            case "tombstone":
                _print(c.tombstone(args.target, args.reason or "cli"))
            case "prune":
                _print(CorpusAnalytics(c).prune_candidates())
            case "synthetic":
                from hydra.corpus.synthetic import SyntheticFoundry, SyntheticRecipe

                async def teacher(prompt: str) -> str:
                    from hydra.core.contracts import HydraRequest, Message

                    return (await rt.kernel.run(HydraRequest(messages=[Message(role="user", content=prompt)],
                                                             use_cache=False), learn=False)).answer
                kind = "arithmetic" if "arithmetic" in args.capability else "python_function" \
                    if args.capability.startswith("coding") else "adversarial"
                anchors = c.search(capability=args.capability.split(".")[0], statuses={"CURATED", "GOLD"},
                                   synthetic=False, limit=20)
                recs = await SyntheticFoundry({"hydra": teacher}).run(SyntheticRecipe(
                    name=f"cli-{args.capability}", capability=args.capability, language=args.language,
                    kind=kind, count=args.count), anchors)
                statuses = [c.ingest(x)[0].training_status.value for x in recs]
                _print({"generated": len(recs), "statuses": {s: statuses.count(s) for s in set(statuses)}})
        return 0
    if cmd == "dataset":
        from hydra.corpus.factory import DatasetSpec

        match args.action:
            case "build":
                spec = DatasetSpec.from_yaml(args.target) if args.target else DatasetSpec(
                    name=args.name or "cli-dataset", format=args.format, record_types=args.record_types or [])
                _print(rt.datasets.build(spec))
            case "list":
                for r in rt.datasets.releases():
                    print(f"{r.id}  {r.format:<9} {r.examples:>7} examples  splits={r.splits}")
            case "verify":
                _print(rt.datasets.verify_release(args.target))
        return 0
    if cmd == "train":
        from hydra.training.lab import (
            SpecialistDiscovery,
            TrainingOrchestrator,
            TrainingRecipe,
            meta_learning_dashboard,
            traces_from_tasks,
        )

        match args.action:
            case "run":
                from hydra.corpus.factory import DatasetSpec

                recipe = TrainingRecipe.from_yaml(args.target)
                spec = DatasetSpec.from_yaml(args.dataset) if args.dataset else None
                _print(await TrainingOrchestrator(rt).run(recipe, spec))
            case "runs":
                _print([r.model_dump(mode="json") for r in TrainingOrchestrator(rt).runs.values()])
            case "specialists":
                traces = traces_from_tasks(await rt.telemetry.recent_tasks(5000), rt.settings.data_dir / "flight")
                sd = SpecialistDiscovery()
                cl = sd.clusters(traces)
                _print({"clusters": [x.model_dump() for x in cl], "proposals": [p.model_dump() for p in sd.propose(cl)]})
            case "dashboard":
                _print(meta_learning_dashboard(await rt.telemetry.recent_runs(), rt.registry))
        return 0
    if cmd == "ip":
        from hydra.ledger.ip import InventionStatus, PriorArtReference, PriorArtSearch, TechnicalEffect, export_bundle

        t = args.target
        match args.action:
            case "propose":
                _print(rt.ip.propose(" ".join(t), problem=args.problem, mechanism=args.mechanism,
                                     solution=args.solution, features=args.feature, contributors=args.contributor))
            case "list":
                _print(rt.ip.portfolio())
            case "status":
                _print(rt.ip.set_status(t[0], InventionStatus(t[1]), args.actor))
            case "effect":
                _print(rt.ip.add_effect(TechnicalEffect(invention_id=t[0], metric=args.metric,
                                                        baseline_value=args.baseline, experimental_value=args.value,
                                                        unit=args.unit, lower_is_better=not args.higher_is_better)))
            case "prior-art":
                refs = [PriorArtReference(identifier=r.split(":")[0],
                                          overlapping_features=r.split(":", 1)[1].split(",") if ":" in r else [])
                        for r in args.reference]
                rt.ip.add_prior_art(PriorArtSearch(invention_id=t[0], references=refs, searcher=args.actor))
                _print(rt.ip.feature_matrix(t[0]))
            case "timeline":
                _print(rt.ip.timeline(t[0]))
            case "bundle":
                p = export_bundle(rt.ip, t[0], Path("ip-bundles"), rt.signer)
                print(p)
        return 0
    if cmd == "ledger":
        match args.action:
            case "verify":
                _print(rt.ledger.verify())
            case "anchor":
                _print(rt.ledger.anchor_now())
            case "proof":
                _print(rt.ledger.proof(args.sequence))
            case "events":
                if args.object:
                    ot, _, oid = args.object.partition(":")
                    evs = rt.ledger.for_object(ot, oid)
                else:
                    evs = list(rt.ledger.events())
                for e in evs[-args.limit:]:
                    print(f"{e.sequence:>6} {e.created_at[:19]} {e.event_type:<28} {e.object_type}:{e.object_id} "
                          f"{e.event_hash[:12]}")
        return 0
    if cmd == "license":
        from hydra.ledger.licenses import LicenseRecord, installed_package_licenses, summary

        if args.action == "packages":
            _print(summary(installed_package_licenses()))
            return 0
        comps = [LicenseRecord(artifact_id=c.split("=")[0], artifact_type="component",
                               license_id=c.split("=", 1)[1] if "=" in c else None) for c in args.component]
        _print(rt.licenses.evaluate(args.target, comps))
        return 0
    if cmd == "bom":
        from hydra.ledger.bom import data_bom_from_release, model_bom_from_factory, write_bom_bundle

        models = [model_bom_from_factory(rt.factory, a) for a in args.artifact]
        _print(write_bom_bundle(Path(args.out), models=models,
                                datasets=[data_bom_from_release(r) for r in rt.datasets.releases()]))
        return 0
    if cmd == "release":
        from hydra.ledger.release import ENVIRONMENTS, ReleaseBuilder, promote, verify_release

        t = args.target
        match args.action:
            case "build":
                p = ReleaseBuilder(rt.settings.data_dir / "releases", rt.signer, rt.ledger).build(
                    t[0], datasets=[r.model_dump(mode="json") for r in rt.datasets.releases()][-5:])
                _print({"path": str(p), **verify_release(p)})
            case "verify":
                _print(verify_release(Path(t[0])))
            case "promote":
                _print(promote(Path(t[0]), t[1].upper(), {"unit": True, "eval": True, "security": True}, rt.signer,
                               rt.ledger))
            case "gate":
                from hydra.ledger.release import ReleaseArtifact, ReleaseGate

                _print(ReleaseGate(rt.ip, rt.licenses, rt.ledger).evaluate(
                    ReleaseArtifact(id=t[0], kind="code", path=t[0]), t[1] if len(t) > 1 else "public"))
        _ = ENVIRONMENTS
        return 0
    if cmd == "replay":
        from hydra.replay import ReplayEngine, replay_traces

        if args.traces:
            cand = json.loads(Path(args.config).read_text()) if args.config else {}
            _print(replay_traces(rt, await rt.telemetry.recent_tasks(args.traces), cand))
            return 0
        eng = ReplayEngine(rt)
        repl = dict(x.split("=", 1) for x in args.replace_model)
        if args.mode == "audit" and not repl:
            _print(await eng.audit(args.task))
        else:
            _print(await eng.rerun(args.task, replace_models=repl or None))
        return 0
    if cmd == "redteam":
        from hydra.governance.redteam import RedTeam

        res = await RedTeam(rt).run()
        for r in res:
            print(f"{'✔' if r.passed else '✘'} {r.id:<24} {r.category:<11} {json.dumps(r.details, default=str)[:100]}")
        return 0 if all(r.passed for r in res) else 3
    if cmd == "doctor":
        from hydra.governance.invariants import check_invariants, definition_of_done, summary

        print("HYDRA 1.0 System Contract")
        for c in await check_invariants(rt):
            print(f"  {c.status:<8} {c.id:<4} {c.title}")
        rows = await definition_of_done(rt, run_recovery=not args.no_recovery)
        print("\nDefinition of Done")
        for r in rows:
            print(f"  {r.status:<8} {r.title}")
        print(summary(rows))
        return 0
    if cmd == "e2e":
        from hydra.evals.e2e import run_e2e

        rep = await run_e2e(rt, limit=args.limit, categories=set(args.category) if args.category else None)
        _print({"dashboard": rep.dashboard, "by_category": rep.by_category})
        return 0
    if cmd == "discover":
        from hydra.discovery import CapabilityDiscovery

        cd = CapabilityDiscovery(rt.evaluator, rt.settings.data_dir / "discovery")
        prof = await cd.discover(rt.registry.get(args.model))
        for k, v in sorted(prof.fingerprint.items()):
            print(f"  {k:<28} {v.score:.3f}  CI [{v.lower:.2f}, {v.upper:.2f}]  N={v.sample_size}")
        if args.apply:
            _print(CapabilityDiscovery.apply(prof, rt.registry))
        return 0
    if cmd == "translate":
        from hydra.edge.translation import TranslationEngine, TranslationRequest

        text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
        res = await TranslationEngine(rt).translate(TranslationRequest(
            text=text, target_language=args.to, source_language=args.source, glossary_name=args.glossary,
            domain=args.domain, model=args.model))
        print(res.translation)
        print(f"\n— {res.source_language}->{res.target_language} model={res.model} chunks={res.chunks} "
              f"glossary={res.glossary_compliance} {res.latency_ms:.0f} ms", file=sys.stderr)
        return 0
    if cmd == "glossary":
        from hydra.edge.translation import GlossaryStore

        store = GlossaryStore(rt.settings.data_dir / "glossaries.json", docs=rt.documents)
        match args.action:
            case "set":
                _print(store.put(args.name, {k: str(v) for k, v in _kv(args.terms).items()}))
            case "show":
                _print(store.get(args.name))
            case "list":
                _print(store.names())
        return 0
    if cmd == "mcp":
        from hydra.protocols.mcp import MCPServer

        await MCPServer(rt, set(args.tools) if args.tools else None).serve_stdio()
        return 0
    if cmd == "mcp-client":
        from hydra.protocols.mcp import MCPClient

        cmdline = [x for x in args.command if x != "--"]
        client = MCPClient(cmdline, Path(cmdline[0]).stem)
        await client.start()
        _print({"server": client.server_info, "tools": [t["name"] for t in client.tools]})
        await client.close()
        return 0
    if cmd == "cluster":
        if args.action == "nodes":
            from hydra.cluster.nodes import detect_local_node

            rt.nodes.heartbeat(detect_local_node(rt.settings.node_id or None, rt.settings.ollama_base_url))
            _print({"summary": rt.nodes.summary(), "nodes": [n.model_dump() for n in rt.nodes.nodes.values()]})
        else:
            from hydra.cluster.nodes import detect_local_node
            from hydra.core.contracts import TaskType

            rt.nodes.heartbeat(detect_local_node(rt.settings.node_id or None, rt.settings.ollama_base_url))
            tt = TaskType(args.task_type)
            _print([p.model_dump() for p in rt.scheduler.place(rt.registry.available(), quality_of=lambda m: m.quality(tt),
                                                               mode=args.mode)][:8])
        return 0
    if cmd == "worker":
        from hydra.cluster.fabric import run_fabric_worker
        from hydra.core.contracts import HydraRequest

        async def handle(item):
            req = HydraRequest.model_validate(item.payload.get("request") or {
                "messages": [{"role": "user", "content": item.payload.get("prompt", "")}]})
            r = await rt.lab.serve(req)
            return {"answer": r.answer, "confidence": r.meta.confidence, "task_id": r.meta.task_id}
        print(f"fabric worker for {args.capability} (Ctrl+C to stop)", file=sys.stderr)
        n = await run_fabric_worker(rt.queue, args.capability, handle, once=args.once)
        print(f"processed {n}", file=sys.stderr)
        return 0
    if cmd == "flags":
        if args.action == "set":
            _print(rt.flags.set(args.name, args.value))
        else:
            _print(rt.flags.snapshot())
        return 0
    if cmd == "config":
        match args.action:
            case "show":
                _print(rt.configs.current(args.env))
            case "commit":
                _print(rt.configs.commit(args.env, _kv(args.values), "cli"))
            case "history":
                _print([c.model_dump() for c in rt.configs.history(args.env)])
            case "rollback":
                _print(rt.configs.rollback(args.env, args.version, "cli"))
        return 0
    if cmd == "sync":
        from hydra.edge.sync import SyncBundle, SyncCursor, export_delta, import_delta, save_bundle, trusted_sync_keys

        if args.action == "export":
            b = export_delta(rt, SyncCursor(world_version=args.world_version, corpus_offset=args.corpus_offset),
                             args.origin or rt.settings.node_id or "edge")
            print(save_bundle(b, Path(args.file)))
        else:
            b = SyncBundle.model_validate_json(Path(args.file).read_text(encoding="utf-8"))
            # Never trust the key embedded in the bundle itself: a self-signed bundle proves nothing.
            keys = trusted_sync_keys(rt) | {Path(k).read_text(encoding="utf-8") for k in args.trust_key}
            _print(import_delta(rt, b, keys))
        return 0
    raise SystemExit(f"unknown command {cmd}")


def run_without_runtime(args, settings) -> int:
    cmd = args.cmd
    if cmd == "backup":
        from hydra.governance.recovery import backup

        from hydra.core.keystore import KeyStore
        from hydra.core.docstore import open_document_store
        from hydra.core.eventlog import open_log_space
        from hydra.ledger.pg import open_ledger

        ledger = open_ledger(settings.ledger_backend, settings.data_dir / "ledger", None, 0, settings.postgres_url)
        logs = [open_log_space(settings.corpus_backend, settings.postgres_url, "corpus"),
                open_log_space(settings.world_backend, settings.postgres_url, "world"),
                open_log_space(settings.ip_backend, settings.postgres_url, "ip"),
                open_log_space(settings.artifacts_backend, settings.postgres_url, "artifacts"),
                open_log_space(settings.runtime_backend, settings.postgres_url, "runtime"),
                open_log_space(settings.documents_backend, settings.postgres_url, "configs"),
                open_document_store(settings.documents_backend, settings.postgres_url)]
        _print(backup(settings.data_dir, Path(args.out), include_private_keys=args.include_private_keys,
                      postgres_url=settings.postgres_url or None, ledger=ledger, logs=logs,
                      keystore=KeyStore.from_settings(settings) if args.include_private_keys else None))
        return 0
    if cmd == "keys":
        from hydra.core.keystore import export_keys

        written = export_keys(settings, Path(args.out))
        _print({"written": [str(p) for p in written],
                "next": f"kubectl -n hydra create secret generic hydra-keys --from-file={args.out}"})
        return 0
    if cmd == "restore":
        from hydra.artifacts.blobs import open_blobs
        from hydra.governance.recovery import restore

        data_dir = Path(args.data_dir)
        blobs = open_blobs(settings.artifact_objects, data_dir / "artifacts" / "objects",
                           settings.s3_endpoint_url) if settings.artifact_objects else None
        rep = restore(Path(args.archive), data_dir, overwrite=args.overwrite, blobs=blobs)
        _print(rep)
        return 0 if rep.ok else 4
    if cmd == "profile":
        cmd, args.action = "edge", "profile"
    if cmd == "edge":
        from hydra.edge.profiles import detect_profile, llamacpp_cmake_args, resolve_profile
        from hydra.edge.scout import best_fit, scan_gguf, scan_ollama

        if bool(args.gpu) != (args.vram_mb is not None):
            print("--gpu and --vram-mb go together", file=sys.stderr)
            return 2
        p = resolve_profile(args.gpu, args.vram_mb) if args.gpu else detect_profile()
        match args.action:
            case "profile":
                _print({**p.as_dict(), "llamacpp_cmake_args": llamacpp_cmake_args(p)})
            case "scout":
                found = scan_ollama(settings.ollama_base_url, p) + scan_gguf([Path(x) for x in args.dirs], p)
                for m in found:
                    print(f"  {'GPU' if m.fits_gpu else '---'} {m.name:<34} {m.quantization or '':<8} "
                          f"{(m.parameters or 0) / 1e9:5.1f}B  ~{m.estimated_vram_gb} GB  score={m.score}")
                _print(best_fit(found))
            case "residency" | "pin-cpu":
                async def go():
                    from hydra.core.bootstrap import build_runtime
                    from hydra.edge.scout import ResidencyManager

                    rt = await build_runtime(settings)
                    try:
                        rm = ResidencyManager(rt.registry, settings.ollama_base_url, p.vram_gb)
                        _print(rm.pin_small_to_cpu() if args.action == "pin-cpu" else await rm.ensure(args.target))
                    finally:
                        await rt.close()
                asyncio.run(go())
        return 0
    if cmd == "build":
        from hydra.edge.autobuild import apply_manifest, autobuild, save_manifest
        from hydra.ledger.signing import Signer

        model = args.model or __import__("os").environ.get("HYDRA_MODEL")
        if not model:
            raise SystemExit("provide --model (an Ollama tag or a .gguf path) or set HYDRA_MODEL")
        from hydra.core.keystore import KeyStore

        signer = Signer.load_or_create(settings.data_dir / "keys", keystore=KeyStore.from_settings(settings))
        m = asyncio.run(autobuild(model=model, runtime=args.runtime, ollama_url=settings.ollama_base_url,
                                  llama_server=args.llama_server or settings.llama_server or None, signer=signer))
        for r in m.all_results:
            c = r["candidate"]
            print(f"  {'✔' if r.get('stable') else '✘'} ctx={c['context']:<6} ngl={c['gpu_layers']:<3} kv={c['kv_k']} "
                  f"tok/s={r.get('tokens_per_second', 0):<7} ttft={r.get('ttft_ms', '-')} ms vram={r.get('vram_peak_mb', '-')} MB "
                  f"gpu={r.get('fully_on_gpu', '-')} score={r.get('score')} {r.get('error', '')}")
        print(f"manifest: {save_manifest(m, Path(args.output))}")
        if m.selected:
            print(f"selected: {json.dumps(m.selected['candidate'])}")
            if args.apply:
                _print(apply_manifest(m, env_path=Path(".env")))
        return 0 if m.selected else 5
    raise SystemExit(f"unknown command {cmd}")
