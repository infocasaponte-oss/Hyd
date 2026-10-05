# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Wires HYDRA OS from Settings. Infrastructure is optional: without Postgres/Redis/NATS
everything runs in memory; with ``offline`` no model runtime is needed."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from hydra.bus.base import EventBus
from hydra.bus.memory import InMemoryEventBus
from hydra.cache.semantic import SemanticCache
from hydra.core.config import Settings
from hydra.core.events import EventType
from hydra.core.kernel import HydraKernel, KernelConfig
from hydra.evals.engine import EvalEngine
from hydra.evals.suites import load_suites
from hydra.lab.lab import HydraLab
from hydra.memory.compiler import MemoryCompiler
from hydra.memory.embeddings import Embedder, HashingEmbedder, OllamaEmbedder, OpenAIEmbedder
from hydra.memory.failures import FailureMemory
from hydra.memory.retriever import MemoryRetriever
from hydra.memory.store import InMemoryMemoryStore, MemoryStore
from hydra.policy.kernel import PolicyKernel
from hydra.providers.adapter import ModelCompiler
from hydra.providers.base import ModelProvider
from hydra.providers.mock import MockProvider
from hydra.providers.ollama import OllamaProvider
from hydra.providers.openai_compatible import OpenAICompatibleProvider
from hydra.registry.circuit_breaker import CircuitBreaker
from hydra.registry.registry import ModelRegistry, refresh_installed_models
from hydra.registry.runtime_monitor import RuntimeMonitor
from hydra.research.graph import ResearchWorker
from hydra.router.learned import LearnedRoutingPolicy
from hydra.router.router import CognitiveRouter
from hydra.router.observer import DecisionObserver
from hydra.providers.decision import LocalSystemOneProvider
from hydra.training.calibrator import TemperatureCalibrator
from hydra.scheduler.invoker import ModelInvoker
from hydra.scheduler.planner import Planner
from hydra.simulation.engine import Simulator
from hydra.telemetry.metrics import InMemoryTelemetry, TelemetryStore
from hydra.tools.builtin import register_builtin_tools
from hydra.tools.executor import ToolExecutor
from hydra.tools.policy import ToolPolicyEngine
from hydra.tools.registry import ToolRegistry
from hydra.tools.sandbox import Sandbox, build_sandbox
from hydra.verification.verifier import Verifier
from hydra.workers.coder import CoderWorker
from hydra.workers.critic import CriticWorker
from hydra.workers.judge import JudgeWorker
from hydra.workers.perception import PerceptionWorker
from hydra.workers.reasoner import ReasonerWorker
from hydra.workers.synthesizer import SynthesizerWorker

log = logging.getLogger("hydra.bootstrap")

PROVIDER_KINDS = ("ollama", "vllm", "llamacpp", "cloud", "mock")


@dataclass
class HydraRuntime:
    kernel: HydraKernel
    settings: Settings
    bus: EventBus
    registry: ModelRegistry
    providers: dict[str, ModelProvider]
    tools: ToolRegistry
    memory: MemoryStore
    retriever: MemoryRetriever
    memory_compiler: MemoryCompiler
    telemetry: TelemetryStore
    policy: PolicyKernel
    cache: SemanticCache
    failures: FailureMemory
    evaluator: EvalEngine
    lab: HydraLab
    sandbox: Sandbox
    embedder: Embedder
    monitor: RuntimeMonitor | None = None
    factory: Any = None
    event_sink: Any = None
    pool: Any = None
    closers: list[Any] = field(default_factory=list)
    # ---- HYDRA 1.0 planes (all local-first, optional infrastructure) ----
    signer: Any = None
    ledger: Any = None
    artifact_store: Any = None
    world: Any = None
    world_rag: Any = None
    knowledge: Any = None
    corpus: Any = None
    datasets: Any = None
    ip: Any = None
    licenses: Any = None
    workspaces: Any = None
    configs: Any = None
    flags: Any = None
    secrets: Any = None
    policy_dsl: Any = None
    market: Any = None
    nodes: Any = None
    scheduler: Any = None
    queue: Any = None
    tenants: Any = None
    tracer: Any = None
    executor: Any = None
    capture_outbox: Any = None
    documents: Any = None
    _goal_runner: Any = None
    _bg: list[Any] = field(default_factory=list)

    @property
    def goals(self):
        """Planner/Simulator goal runner (created on first use)."""
        if self._goal_runner is None:
            from hydra.planning.runner import GoalRunner

            self._goal_runner = GoalRunner(self)
        return self._goal_runner

    async def close(self) -> None:
        for t in self._bg:
            t.cancel()
        await self.lab.drain()
        if self.monitor is not None:
            await self.monitor.stop()
        try:
            await self.kernel.router.close()
        except Exception:
            log.exception("decision observer close failed")
        for p in {id(p): p for p in self.providers.values()}.values():
            try:
                await p.close()
            except Exception:
                log.exception("provider close failed")
        await self.bus.close()
        if self.pool is not None:
            await self.pool.close()


def build_providers(settings: Settings) -> dict[str, ModelProvider]:
    if settings.offline:
        mock = MockProvider()
        return {kind: mock for kind in PROVIDER_KINDS}
    providers: dict[str, ModelProvider] = {
        "ollama": OllamaProvider(settings.ollama_base_url),
        "vllm": OpenAICompatibleProvider(settings.vllm_base_url, settings.internal_api_key),
        "llamacpp": OpenAICompatibleProvider(settings.llamacpp_base_url, settings.internal_api_key),
        "mock": MockProvider(),
    }
    if settings.cloud_api_key:
        providers["cloud"] = OpenAICompatibleProvider(settings.cloud_base_url, settings.cloud_api_key)
    return providers


def build_embedder(settings: Settings) -> Embedder:
    if settings.offline or settings.embedding_provider == "hashing" or not settings.embedding_model:
        return HashingEmbedder()
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings.ollama_base_url, settings.embedding_model)
    return OpenAIEmbedder(settings.vllm_base_url, settings.embedding_model, settings.internal_api_key)


async def build_bus(settings: Settings) -> EventBus:
    if settings.nats_url:
        from hydra.bus.nats import NatsEventBus

        bus = NatsEventBus(settings.nats_url)
        await bus.connect()
        return bus
    if settings.redis_url:
        from hydra.bus.redis_streams import RedisStreamsEventBus

        return RedisStreamsEventBus(settings.redis_url)
    return InMemoryEventBus()


async def build_runtime(settings: Settings | None = None, **overrides: Any) -> HydraRuntime:
    """Build the engine. ``overrides`` may replace any component (tests, embedding)."""
    settings = settings or Settings()
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    # ---- infrastructure -------------------------------------------------------------
    bus: EventBus = overrides["bus"] if "bus" in overrides else await build_bus(settings)
    pool = event_sink = None
    memory: MemoryStore
    telemetry: TelemetryStore
    if settings.memory_backend == "postgres" and not settings.postgres_url:
        raise ValueError("postgres memory requires HYDRA_POSTGRES_URL")
    if settings.postgres_url and settings.memory_backend in ("auto", "postgres") and "memory" not in overrides:
        from hydra.memory.store import PostgresMemoryStore
        from hydra.persistence.postgres import PostgresEventSink, PostgresTelemetry, create_pool

        pool = await create_pool(settings.postgres_url)
        memory = PostgresMemoryStore(pool)
        telemetry = PostgresTelemetry(pool)
        event_sink = PostgresEventSink(pool)
        await bus.subscribe(None, event_sink)
    else:
        if "memory" in overrides:
            memory = overrides["memory"]
        elif settings.memory_backend == "memory":
            memory = InMemoryMemoryStore()
        else:
            from hydra.memory.sqlite_store import SQLiteMemoryStore
            memory = SQLiteMemoryStore(settings.data_dir / "knowledge-memory.sqlite3", settings.memory_namespace)
        telemetry = overrides.get("telemetry") or InMemoryTelemetry()

    # ---- models ---------------------------------------------------------------------
    providers = overrides.get("providers") or build_providers(settings)
    registry = overrides.get("registry") or ModelRegistry.from_yaml(
        settings.models_config,
        CircuitBreaker(settings.breaker_failures, settings.breaker_cooldown_s),
    )
    if not settings.offline and "registry" not in overrides:
        for m in registry.all():
            if m.provider == "cloud" and not settings.cloud_api_key:
                pass  # disabled below: no credentials
            elif m.endpoint and m.provider in ("vllm", "llamacpp", "cloud"):
                key = f"{m.provider}:{m.id}"
                api_key = settings.cloud_api_key if m.provider == "cloud" else settings.internal_api_key
                providers[key] = OpenAICompatibleProvider(m.endpoint, api_key)
                m.provider = key
            elif m.endpoint and m.provider == "ollama":
                key = f"ollama:{m.id}"
                providers[key] = OllamaProvider(m.endpoint)
                m.provider = key
            if m.provider not in providers:
                m.enabled = False
                log.info("model %s disabled: provider '%s' not configured", m.id, m.provider)

    embedder: Embedder = overrides.get("embedder") or build_embedder(settings)
    retriever = MemoryRetriever(memory, embedder)
    compiler = MemoryCompiler(memory, embedder)

    # ---- policy, cache, failure memory ---------------------------------------------------
    policy = overrides.get("policy") or PolicyKernel.from_yaml(settings.policy_config)
    cache = SemanticCache(embedder, memory)
    from hydra.core.docstore import open_document_store

    documents = overrides.get("documents") or open_document_store(settings.documents_backend, settings.postgres_url)
    failures = FailureMemory(settings.data_dir / "failure_memory.json", docs=documents)
    for et in (EventType.MODEL_COMPLETED, EventType.MODEL_FAILED, EventType.TOOL_COMPLETED, EventType.TOOL_FAILED):
        await bus.subscribe(et, failures.observe)

    # ---- tools ----------------------------------------------------------------------
    tools = ToolRegistry()
    sandbox = overrides.get("sandbox") or build_sandbox(
        settings.sandbox_backend, settings.sandbox_image, settings.workspace_dir,
        settings.sandbox_workspace_source or None)
    register_builtin_tools(tools, sandbox, memory_search=retriever.search)
    from hydra.tools.workspace import WorkspaceManager, register_workspace_tools

    register_workspace_tools(tools, sandbox)

    # ---- HYDRA 1.0 planes: ledger, artifacts, world, corpus, IP, governance ---------------
    from hydra.artifacts.store import ArtifactStore
    from hydra.core.capture import CapturePipeline
    from hydra.core.capture_outbox import CaptureOutbox
    from hydra.core.capture_outbox_pg import open_outbox_store
    from hydra.corpus.capture import CapturePolicy
    from hydra.corpus.dedup import ContaminationGuard, Deduplicator
    from hydra.corpus.factory import DatasetFactory
    from hydra.corpus.gates import CorpusCurator
    from hydra.corpus.store import CorpusStore
    from hydra.core.eventlog import open_log_space
    from hydra.artifacts.blobs import open_blobs
    from hydra.governance.config_registry import ConfigRegistry, FeatureFlags
    from hydra.governance.policy_dsl import PolicyEngine
    from hydra.governance.secrets import SecretsBroker
    from hydra.ledger.pg import open_ledger
    from hydra.ledger.ip import IPRegistry
    from hydra.ledger.licenses import LicenseEngine
    from hydra.core.keystore import KeyStore
    from hydra.ledger.signing import Signer
    from hydra.market import CapabilityMarket
    from hydra.world.knowledge import GraphRAG, KnowledgeCompiler
    from hydra.world.model import WorldModel

    data = settings.data_dir
    keystore = overrides.get("keystore") or KeyStore.from_settings(settings)
    signer = overrides.get("signer") or Signer.load_or_create(data / "keys", keystore=keystore)
    ledger = open_ledger(settings.ledger_backend, data / "ledger", signer, settings.ledger_anchor_every,
                         settings.postgres_url)
    artifact_store = ArtifactStore(
        data / "artifacts", logs=open_log_space(settings.artifacts_backend, settings.postgres_url, "artifacts"),
        blobs=open_blobs(settings.artifact_objects, data / "artifacts" / "objects", settings.s3_endpoint_url))
    world = WorldModel(data / "world", logs=open_log_space(settings.world_backend, settings.postgres_url, "world"))
    world_rag = GraphRAG(world)

    def family_of(model_id: str) -> str:
        m = registry.models.get(model_id)
        return (m.logical_model or m.physical_name.split(":")[0]) if m else model_id

    knowledge = KnowledgeCompiler(world, family_of=family_of)
    corpus = CorpusStore(data / "corpus", CorpusCurator(
        dedup=Deduplicator(), contamination=ContaminationGuard.from_suites(load_suites(settings.evals_dir))),
        ledger=ledger, logs=open_log_space(settings.corpus_backend, settings.postgres_url, "corpus"))
    datasets = DatasetFactory(corpus, ledger)
    ip = IPRegistry(data / "ip", ledger, logs=open_log_space(settings.ip_backend, settings.postgres_url, "ip"))
    licenses = LicenseEngine.from_yaml(settings.licenses_config)
    workspaces = WorkspaceManager(data / "workspaces")
    configs = ConfigRegistry(data / "configs", ledger,
                             logs=open_log_space(settings.documents_backend, settings.postgres_url, "configs"))
    flags = FeatureFlags(data / "flags.json", docs=documents)
    secrets = SecretsBroker(data / "secrets", audit=lambda et, p: ledger.append(et, p, object_type="secret",
                                                                                 object_id=p.get("ref", "")),
                            keystore=keystore, docs=documents)
    policy_dsl = PolicyEngine.from_yaml(settings.policy_rules_config)
    market = CapabilityMarket()
    executor = ToolExecutor(tools, ToolPolicyEngine(policy), bus, simulator=Simulator(), secrets=secrets,
                            policy_dsl=policy_dsl)
    from hydra.cluster.capacity import TenantRegistry
    from hydra.cluster.fabric import open_work_queue
    from hydra.cluster.nodes import NodeRegistry
    from hydra.cluster.scheduler import GlobalScheduler

    nodes = NodeRegistry(heartbeat_ttl_s=max(30.0, settings.heartbeat_interval_s * 3))
    scheduler = GlobalScheduler(nodes)
    queue = open_work_queue(settings.fabric_backend, data / "fabric" / "queue.db", settings.postgres_url)

    def config_ref():
        cur = configs.current("production")
        return cur.ref if cur else None

    capture = CapturePipeline(
        world=world, compiler=knowledge, corpus=corpus, ledger=ledger, artifacts=artifact_store,
        flight_dir=data / "flight",
        capture_policy=CapturePolicy(auto_training_max_sensitivity=settings.corpus_auto_training_max_sensitivity),
        policy_version=policy_dsl.version, config_ref=config_ref, registry=registry,
        outbox=CaptureOutbox(data / "capture_outbox.db", ledger=ledger, corpus=corpus,
                             store=open_outbox_store(settings.outbox_backend, data / "capture_outbox.db",
                                                     settings.postgres_url)))

    # ---- backend health ------------------------------------------------------------
    # Probe providers before the first routing decision. Registry configuration remains
    # intact; only the runtime availability view is updated.
    if not settings.offline and "registry" not in overrides:
        health = await asyncio.gather(
            *(provider.health() for provider in providers.values()),
            return_exceptions=True,
        )
        for (name, _), healthy in zip(providers.items(), health):
            registry.set_provider_health(name, healthy is True)
            if healthy is not True:
                log.info("provider %s unavailable; models will be excluded from routing", name)
        for name, ids in (await refresh_installed_models(registry, providers)).items():
            if ids:
                log.warning("provider %s does not have %s installed; excluded from routing", name, ", ".join(ids))

    # ---- cognition ------------------------------------------------------------------
    model_compiler = ModelCompiler()
    invoker = ModelInvoker(providers, registry, hedge_after_ms=settings.hedge_after_ms, compiler=model_compiler)
    classifier = classifier_model = None
    if settings.router_model and settings.router_model in registry.models:
        rm = registry.get(settings.router_model)
        classifier, classifier_model = providers.get(rm.provider), rm.physical_name

    domains = [d.strip() for d in settings.network_domains.split(",") if d.strip()] or None
    coder = CoderWorker(invoker, tools, executor)
    learned = LearnedRoutingPolicy()
    try:
        learned.fit(await telemetry.recent_runs())
    except Exception:
        log.debug("no telemetry to fit the learned router yet")
    observer = None
    if settings.hyd_enabled:
        from hydra.hyd.continual_controller import controller_class
        observer = controller_class(settings.hyd_model_path)(settings.hyd_model_path, settings.hyd_calibration_path,
                                 settings.hyd_authority_evidence_path)
        ranker = getattr(getattr(observer, 'engine', None), 'ranker', None)
        if not settings.offline and getattr(ranker, 'spec', {}).get('kind') in ('minilm', 'minilm-finetuned'):
            try:
                await asyncio.to_thread(ranker.vectors, ['Synthetic encoder readiness probe'])
                observer.encoder_ready = True
            except Exception as exc:
                observer.encoder_ready = False
                log.warning('Hyd encoder startup readiness failed: %s', type(exc).__name__)
    elif settings.decision_local_model_path:
        if not settings.decision_local_calibration_path:
            raise ValueError("local decision observer requires model-bound calibration")
        from hydra.router.local_observer import CalibratedLocalObserver
        observer = CalibratedLocalObserver(settings.decision_local_model_path,
                                          settings.decision_local_calibration_path)
    elif settings.decision_shadow_endpoint and not settings.offline:
        calibrator = (TemperatureCalibrator.load(settings.decision_calibrator_path)
                      if settings.decision_calibrator_path else None)
        from hydra.router.decision_contract import CRITERIA
        observer = DecisionObserver(LocalSystemOneProvider(
            endpoint=settings.decision_shadow_endpoint, model=settings.decision_shadow_model,
            timeout=settings.decision_shadow_timeout_s), settings.decision_shadow_timeout_s,
            calibrator=calibrator, criteria=CRITERIA if settings.decision_full_contract else None)
    authority = observer if settings.hyd_enabled else None
    if settings.decision_authority_evidence_path and not settings.hyd_enabled:
        if observer is None:
            raise ValueError("decision authority requires a configured observer")
        import json
        from hydra.router.decision_authority import DecisionAuthority
        authority_evidence = json.loads(settings.decision_authority_evidence_path.read_text(encoding="utf-8"))
        authority = DecisionAuthority.from_evidence(authority_evidence, observer.model)
        if authority.enabled:
            if (not isinstance(observer, DecisionObserver) or observer.calibrator is None
                    or observer.calibrator.model_run != authority_evidence["model_revision"]):
                raise ValueError("decision authority requires checkpoint-bound Kev calibration")
            observer.expected_run = authority_evidence["model_revision"]
    kernel = HydraKernel(
        router=CognitiveRouter(classifier, classifier_model, observer=observer, authority=authority),
        registry=registry,
        planner=Planner(),
        reasoner=ReasonerWorker(invoker),
        coder=coder,
        critic=CriticWorker(invoker),
        judge=JudgeWorker(invoker),
        synthesizer=SynthesizerWorker(invoker),
        verifier=Verifier(),
        bus=bus,
        retriever=retriever,
        memory_compiler=compiler,
        telemetry=telemetry,
        workspace=settings.workspace_dir,
        network_domains=domains,
        public_web_enabled=settings.public_web_enabled and not settings.offline,
        policy=policy,
        cache=cache,
        failures=failures,
        learned=learned,
        perception=PerceptionWorker(invoker),
        research=ResearchWorker(invoker, coder),
        config=KernelConfig(time_scale=settings.budget_time_scale, capture=settings.capture,
                            deterministic_first=settings.deterministic_first),
        capture=capture,
        world_rag=world_rag,
        policy_dsl=policy_dsl,
        solvers=market.solvers,
        scheduler=scheduler if settings.cluster_rerank else None,
    )
    market.sync_registry(registry, tools)

    evaluator = EvalEngine(providers, sandbox, tools, model_compiler, load_suites(settings.evals_dir))
    lab = HydraLab(kernel, evaluator, settings.data_dir / "lab.json", bus, docs=documents)

    monitor = None
    if settings.runtime_monitor and not settings.offline and "registry" not in overrides:
        monitor = RuntimeMonitor(
            registry, settings.monitor_interval_s, settings.ollama_base_url, providers=providers
        )
        monitor.start()

    runtime = HydraRuntime(
        kernel=kernel, settings=settings, bus=bus, registry=registry, providers=providers, tools=tools,
        memory=memory, retriever=retriever, memory_compiler=compiler, telemetry=telemetry,
        policy=policy, cache=cache, failures=failures, evaluator=evaluator, lab=lab, sandbox=sandbox,
        embedder=embedder, monitor=monitor, event_sink=event_sink, pool=pool,
        signer=signer, ledger=ledger, artifact_store=artifact_store, world=world, world_rag=world_rag,
        knowledge=knowledge, corpus=corpus, datasets=datasets, ip=ip, licenses=licenses, workspaces=workspaces,
        configs=configs, flags=flags, secrets=secrets, policy_dsl=policy_dsl, market=market, nodes=nodes,
        scheduler=scheduler, queue=queue, tenants=TenantRegistry(), executor=executor,
    )
    from hydra.observability.tracing import CognitiveTracer

    runtime.tracer = CognitiveTracer(settings.otel_endpoint or None, registry=registry)
    runtime.capture_outbox = capture.outbox
    if settings.capture:
        async def capture_outbox_loop() -> None:  # retries deferred ledger/corpus writes
            while True:
                try:
                    await asyncio.to_thread(capture.outbox.drain)
                except Exception:
                    log.exception("capture outbox drain failed")
                await asyncio.sleep(settings.capture_outbox_poll_s)
        runtime._bg.append(asyncio.create_task(capture_outbox_loop()))
    await bus.subscribe(None, runtime.tracer.observe)
    if not settings.offline and "registry" not in overrides:
        from hydra.cluster.nodes import detect_local_node

        async def heartbeat_loop() -> None:
            while True:
                try:
                    node = await asyncio.to_thread(detect_local_node, settings.node_id or None,
                                                   settings.ollama_base_url)
                    nodes.heartbeat(node)
                except Exception:
                    log.debug("local node heartbeat failed", exc_info=True)
                await asyncio.sleep(settings.heartbeat_interval_s)
        runtime._bg.append(asyncio.create_task(heartbeat_loop()))
    from hydra.model_factory.service import ModelFactory  # local import: optional heavy subsystem

    runtime.factory = ModelFactory.from_settings(settings, registry=registry, evaluator=evaluator,
                                                 telemetry=telemetry, bus=bus, lab=lab, docs=documents)
    runtime.documents = documents
    if settings.require_shared_state:
        check_shared_state(runtime, keystore)
    return runtime


def _postgres_available(backend: str, postgres_url: str) -> bool:
    if backend == "postgres":
        return True
    if backend != "auto" or not postgres_url:
        return False
    import importlib.util

    return importlib.util.find_spec("psycopg") is not None


def check_shared_state(runtime: HydraRuntime, keystore) -> None:
    """HYDRA_REQUIRE_SHARED_STATE: every plane must resolve to PostgreSQL and the keys must not live in
    the data directory; otherwise refuse to start, naming what is local."""
    s = runtime.settings
    planes = {
        "ledger (HYDRA_LEDGER_BACKEND)": runtime.ledger.backend,
        "corpus (HYDRA_CORPUS_BACKEND)": runtime.corpus.logs.backend,
        "World Model (HYDRA_WORLD_BACKEND)": runtime.world.logs.backend,
        "IP registry (HYDRA_IP_BACKEND)": runtime.ip.logs.backend,
        "artifact manifests (HYDRA_ARTIFACTS_BACKEND)": runtime.artifact_store.logs.backend,
        "fabric queue (HYDRA_FABRIC_BACKEND)": runtime.queue.backend,
        "capture outbox (HYDRA_OUTBOX_BACKEND)": getattr(runtime.capture_outbox.outbox, "backend", "sqlite")
        if runtime.capture_outbox is not None else "postgres",
        "documents (HYDRA_DOCUMENTS_BACKEND)": runtime.documents.backend,
        "config sets (HYDRA_DOCUMENTS_BACKEND)": runtime.configs.logs.backend,
    }
    if s.runtime_api:
        planes["runtime line (HYDRA_RUNTIME_BACKEND)"] = (
            "postgres" if _postgres_available(s.runtime_backend, s.postgres_url) else "file")
    local = [name for name, backend in planes.items() if backend != "postgres"]
    if keystore is not None and not keystore.secure():
        local.append("private keys (set HYDRA_KEYS_DIR to a mounted secret, or HYDRA_KEY_<NAME>)")
    if local:
        raise RuntimeError("HYDRA_REQUIRE_SHARED_STATE is set but these are local to this node: "
                           + "; ".join(local) + ". Set HYDRA_POSTGRES_URL (and install the postgres extra) "
                           "or unset HYDRA_REQUIRE_SHARED_STATE for a single node.")
