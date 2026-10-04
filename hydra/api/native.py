# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from hydra import __version__
from hydra.artifacts.blobs import open_blobs
from hydra.core.eventlog import open_log_space
from hydra.artifacts.task_store import ArtifactStore
from hydra.world.task_beliefs import BeliefStore
from hydra.corpus.artifact_candidates import CorpusStore
from hydra.core.native_bootstrap import bootstrap_runtime
from hydra.core.request_budget import RequestBudget, RequestBudgetExceeded as BudgetExceeded
from hydra.coding.agent import CodeAgent
from hydra.coding.replay_evidence import build_code_replay_evidence
from hydra.verification.code import VerificationMode, VerificationPolicy
from hydra.coding.request import CodingRequest, resolve_repository
from hydra.core.native_config import settings
from hydra.core.native_contracts import HydraTask
from hydra.deploy.deployment import Deployment
from hydra.deploy.deployment_controller import DeploymentController
from hydra.deploy.deployment_controller import LEGACY_OFFSETS, EvidenceRejected
from hydra.deploy.deployment_store import DeploymentStore
from hydra.deploy.deployment_validation import DeploymentArtifactValidator
from hydra.core.native_kernel import HydraKernel
from hydra.corpus.patch_capture import LearningCapture
from hydra.model_factory.contracts import ModelVariant
from hydra.model_factory.model_scout import HashCache, scan_models
from hydra.observability.spans import OtlpSpanExporter
from hydra.observability.spans import SpanRecorder as CognitiveTracer
from hydra.observability.operating import collect_operating_metrics
from hydra.core.outbox_dispatcher import OutboxDispatcher
from hydra.core.outbox_worker import OutboxWorker
from hydra.providers.physical import PhysicalInferenceClient
from hydra.core.durable_events import JsonlEventStore
from hydra.core.runtime_paths import runtime_path
from hydra.provenance.ledger import ProvenanceLedger, ProvenanceRecord
from hydra.providers.local_llm import LocalLLM
from hydra.governance.rate_limit import RateLimit, SlidingWindowRateLimiter
from hydra.deploy.readiness import evaluate_readiness
from hydra.audit.replay import ReplayManifest, ReplayStore
from hydra.audit.executor import AuditReplayExecutor
from hydra.deploy.bridge import RuntimeBridge
from hydra.deploy.events import RuntimeEventEmitter
from hydra.deploy.runtime_evidence import RuntimeEvidenceStore
from hydra.deploy.executor import RuntimeExecutor
from hydra.deploy.runtime_health import RuntimeHealth
from hydra.core.native_stores import open_runtime_stores
from hydra.tools.oci_sandbox import OciSandbox
from hydra.api.native_access import SecurityConfig, require_admin_access, require_api_access
from hydra.audit.access import SecurityAudit
from hydra.deploy.traffic_router import TrafficRouter
from hydra.edge.native_translation import GlossaryStore, TranslationService
from hydra.tools.native_workspace import WorkspaceManager

llm = LocalLLM(settings.llm_url)
budget = RequestBudget(
    settings.max_input_chars,
    settings.max_output_tokens,
    settings.max_translation_chunks,
)
glossaries = GlossaryStore()
model_hash_cache = HashCache(Path(settings.runtime_db).parent / "model-hashes.json")
translations = TranslationService(llm, budget, glossaries)
runtime_logs = open_log_space(settings.runtime_backend, settings.postgres_url, "runtime")
_shared = runtime_logs.backend == "postgres"
artifacts = ArtifactStore(
    blobs=open_blobs(settings.artifact_objects, Path(settings.data_dir) / "artifacts" / "objects",
                     settings.s3_endpoint_url) if _shared else None,
    log=runtime_logs.open(runtime_path("artifacts.jsonl"), ArtifactStore.STREAM) if _shared else None,
)
provenance = ProvenanceLedger(log=runtime_logs.open(runtime_path("provenance.jsonl"), ProvenanceLedger.STREAM))
workspaces = WorkspaceManager(
    source_root=settings.repositories_root,
    max_files=settings.workspace_max_files,
    max_bytes=settings.workspace_max_bytes,
)
learning = LearningCapture(
    artifacts_store=artifacts,
    beliefs=BeliefStore(log=runtime_logs.open(runtime_path("beliefs.jsonl"), BeliefStore.STREAM)),
    corpus=CorpusStore(log=runtime_logs.open(runtime_path("corpus.jsonl"), CorpusStore.STREAM)),
)
replay_store = ReplayStore(
    log=runtime_logs.open(runtime_path("replay.jsonl"), ReplayStore.STREAM) if _shared else None
)
deployment_artifact_validator = DeploymentArtifactValidator(settings.models_dir)
deployment_store = DeploymentStore(
    settings.deployments_file,
    validator=deployment_artifact_validator,
    log=runtime_logs.open(Path(settings.deployments_file).with_suffix(".jsonl"), DeploymentStore.STREAM)
    if runtime_logs.backend == "postgres" else None,
)
deployment_registry = deployment_store.load()
runtime_stores = open_runtime_stores(
    settings.runtime_db, settings.postgres_url if runtime_logs.backend == "postgres" else ""
)
deployment_evidence_store = runtime_stores.deployment_evidence
operating_metrics_store = runtime_stores.operating_metrics
runtime_evidence = RuntimeEvidenceStore(
    log=runtime_logs.open(runtime_path("runtime-evidence.jsonl"), RuntimeEvidenceStore.STREAM)
)
deployment_controller = DeploymentController(
    deployment_registry,
    evidence_store=deployment_evidence_store,
    runtime_evidence=runtime_evidence,
)
if any(LEGACY_OFFSETS[key] in d.metadata for d in deployment_registry.deployments.values() for key in LEGACY_OFFSETS):
    deployment_store.mutate(deployment_registry, lambda _: deployment_controller.migrate_phase_starts())
capture_uow = runtime_stores.capture_uow
kernel = HydraKernel(
    capture_uow=capture_uow,
    tracer=CognitiveTracer(store=runtime_stores.traces,
                           exporter=OtlpSpanExporter(settings.otel_endpoint) if settings.otel_endpoint else None),
    events=JsonlEventStore(log=runtime_logs.open(runtime_path("events.jsonl"), JsonlEventStore.STREAM)),
)
runtime_health_store = runtime_stores.runtime_health
runtime_health = RuntimeHealth(store=runtime_health_store)
physical_inference = PhysicalInferenceClient(deployment_registry)
traffic_router = TrafficRouter(deployment_registry, runtime_health)
runtime_executor = RuntimeExecutor(
    traffic_router,
    runtime_health,
    physical_inference.generate,
    runtime_evidence,
)
runtime_bridge = RuntimeBridge(
    runtime_executor,
    runtime_health,
    RuntimeEventEmitter(kernel.events),
)
kernel.runtime_bridge = runtime_bridge
outbox_dispatcher = OutboxDispatcher(
    capture_uow.outbox,
    kernel.events,
    provenance,
    learning.corpus,
)
outbox_worker = OutboxWorker(capture_uow.outbox, outbox_dispatcher)
security_config = SecurityConfig(
    api_token=settings.api_token,
    admin_token=settings.admin_token,
    client_keys_file=settings.client_keys_file,
)
rate_limiter = SlidingWindowRateLimiter()
security_audit = SecurityAudit(kernel.events)
api_rate_limit = RateLimit(
    requests=settings.api_rate_limit_per_minute,
    window_seconds=60,
)
admin_rate_limit = RateLimit(
    requests=settings.admin_rate_limit_per_minute,
    window_seconds=60,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bootstrap = bootstrap_runtime(outbox_worker)
    worker_task = asyncio.create_task(outbox_worker.run_forever())
    app.state.outbox_worker_task = worker_task
    sync_task = asyncio.create_task(_follow_deployments()) if deployment_store.log is not None else None
    try:
        yield
    finally:
        for task in (worker_task, sync_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


async def _follow_deployments(interval_s: float = 1.0) -> None:
    """Shared deployment registry: adopt promotions and rollbacks made on other nodes."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            await asyncio.to_thread(deployment_store.sync, deployment_registry)
        except Exception:  # noqa: BLE001 - keep following; the next tick retries
            logging.getLogger("hydra.runtime.deployments").exception("deployment registry sync failed")


app = FastAPI(title="HYDRA-SO", version=__version__, lifespan=lifespan)


class ChatRequest(BaseModel):
    __module__ = "hydra.runtime.api"
    message: str
    max_tokens: int = Field(default=1024, ge=1)


class TranslationRequest(BaseModel):
    __module__ = "hydra.runtime.api"
    text: str
    target_language: str
    source_language: str | None = None
    glossary_id: str | None = None


class GlossaryRequest(BaseModel):
    __module__ = "hydra.runtime.api"
    terms: dict[str, str] = Field(default_factory=dict)


class DeploymentRegisterRequest(BaseModel):
    __module__ = "hydra.runtime.api"
    variant: ModelVariant
    capabilities: list[str] = Field(min_length=1)
    generation: int = Field(default=0, ge=0)




@app.get("/health")
async def health() -> dict:
    return {"hydra": "ok", "version": __version__}


@app.get("/ready")
async def ready(response: Response) -> dict:
    llm_healthy = await llm.health()
    worker_task = getattr(app.state, "outbox_worker_task", None)
    worker_running = worker_task is not None and not worker_task.done()
    status = evaluate_readiness(
        outbox=capture_uow.outbox,
        events=kernel.events,
        provenance=provenance,
        llm_healthy=bool(llm_healthy),
        worker_running=worker_running,
        max_pending=settings.readiness_max_pending,
        max_oldest_pending_age_seconds=settings.readiness_max_pending_age_seconds,
    )
    if not status.ready:
        response.status_code = 503
    return {
        "ready": status.ready,
        "reasons": list(status.reasons),
        "pending_outbox": status.pending_outbox,
        "dead_letters": status.dead_letters,
        "events_integrity": status.events_integrity,
        "provenance_integrity": status.provenance_integrity,
        "llm_healthy": status.llm_healthy,
        "worker_running": status.worker_running,
        "oldest_pending_age_seconds": status.oldest_pending_age_seconds,
    }


@app.post("/v1/chat")
async def chat(req: ChatRequest, request: Request) -> dict:
    identity = require_api_access(request, security_config)
    rate_limiter.check(f"chat:{identity}", api_rate_limit)
    try:
        budget.validate_input(req.message)
        answer = await llm.chat(
            [{"role": "user", "content": req.message}],
            max_tokens=budget.output_tokens(req.max_tokens),
        )
        return {"answer": answer}
    except BudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Local model unavailable") from exc


@app.post("/v1/translate")
async def translate(req: TranslationRequest, request: Request) -> dict:
    identity = require_api_access(request, security_config)
    rate_limiter.check(f"translate:{identity}", api_rate_limit)
    try:
        answer = await translations.translate(
            req.text, req.target_language, req.source_language, req.glossary_id
        )
        return {"translation": answer, "target_language": req.target_language}
    except BudgetExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Local model unavailable") from exc


@app.put("/v1/glossaries/{glossary_id}")
async def put_glossary(
    glossary_id: str,
    req: GlossaryRequest,
    request: Request,
) -> dict:
    identity = require_api_access(request, security_config)
    rate_limiter.check(f"glossary:{identity}", api_rate_limit)
    try:
        return glossaries.save(glossary_id, req.terms)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/models")
async def models(request: Request) -> dict:
    identity = require_api_access(request, security_config)
    rate_limiter.check(f"models:{identity}", api_rate_limit)
    # Hashing multi-GB GGUF files is blocking I/O: keep it off the event loop and cached.
    artifacts = await asyncio.to_thread(scan_models, settings.models_dir, model_hash_cache)
    return {"count": len(artifacts), "models": [item.as_dict() for item in artifacts]}


@app.post("/hydra/v1/tasks/route")
async def route_task(task: HydraTask, request: Request) -> dict:
    """Create and route a native HYDRA task without executing external side effects.

    Preparing the task writes audit events, so the route requires API access."""
    identity = require_api_access(request, security_config)
    rate_limiter.check(f"task-route:{identity}", api_rate_limit)
    try:
        trace_id, route = kernel.prepare(task)
        return {
            "task_id": str(task.id),
            "status": task.status.value,
            "trace_id": trace_id,
            "route": route.model_dump(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/hydra/v1/tasks/execute")
async def execute_task(task: HydraTask, request: Request) -> dict:
    """Execute a safe local cognitive task through the HYDRA kernel."""
    identity = require_api_access(request, security_config)
    rate_limiter.check(f"task-execute:{identity}", api_rate_limit)
    try:
        result = await kernel.run(task, llm)
        return result.model_dump(mode="json")
    except Exception as exc:
        from hydra.scheduler.native_executor import UnsafePlan
        if isinstance(exc, UnsafePlan):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail="HYDRA execution failed") from exc




@app.get("/hydra/v1/admin/replay/{task_id}/audit")
async def audit_replay(task_id: UUID, request: Request) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-replay-audit:{identity}", admin_rate_limit)
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/replay/audit",
        outcome="allowed",
        identity_hash=identity,
        aggregate_id=task_id,
    )
    manifest = replay_store.get(task_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Replay manifest not found")

    result = AuditReplayExecutor(
        events=kernel.events,
        provenance=provenance,
        artifact_root=artifacts.root,
        artifacts=artifacts,
    ).audit(manifest)
    if not result.valid:
        return {
            "valid": False,
            "checked_artifacts": result.checked_artifacts,
            "event_records": result.event_records,
            "provenance_records": result.provenance_records,
            "error": result.error,
        }
    return {
        "valid": True,
        "checked_artifacts": result.checked_artifacts,
        "event_records": result.event_records,
        "provenance_records": result.provenance_records,
        "error": None,
    }


@app.get("/hydra/v1/admin/metrics")
async def admin_metrics(request: Request) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-metrics:{identity}", admin_rate_limit)
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/metrics",
        outcome="allowed",
        identity_hash=identity,
    )
    metrics = collect_operating_metrics(
        outbox=capture_uow.outbox,
        traces=kernel.tracer.store,
        deployments=deployment_registry,
    )
    snapshot_id = operating_metrics_store.append(metrics)
    return {
        "snapshot_id": snapshot_id,
        "outbox_pending": metrics.outbox_pending,
        "outbox_dead_letters": metrics.outbox_dead_letters,
        "oldest_pending_age_seconds": metrics.oldest_pending_age_seconds,
        "spans_total": metrics.spans_total,
        "spans_error": metrics.spans_error,
        "avg_span_duration_ms": metrics.avg_span_duration_ms,
        "spans_by_name": metrics.spans_by_name,
        "deployments_by_state": metrics.deployments_by_state,
    }


@app.get("/hydra/v1/admin/metrics/history")
async def admin_metrics_history(request: Request, limit: int = 100) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-metrics-history:{identity}", admin_rate_limit)
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/metrics/history",
        outcome="allowed",
        identity_hash=identity,
    )
    try:
        snapshots = operating_metrics_store.recent(limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"count": len(snapshots), "snapshots": snapshots}


@app.get("/hydra/v1/admin/deployments")
async def list_deployments(request: Request) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-deployments-list:{identity}", admin_rate_limit)
    items = sorted(
        deployment_registry.deployments.values(),
        key=lambda item: (item.generation, str(item.variant_id)),
    )
    return {
        "count": len(items),
        "deployments": [
            {
                "variant_id": str(item.variant_id),
                "state": item.state.value,
                "generation": item.generation,
                "capabilities": sorted(item.capabilities),
                "quantization": item.variant.quantization,
                "artifact_sha256": item.variant.artifact_sha256,
            }
            for item in items
        ],
    }


@app.post("/hydra/v1/admin/deployments/register")
async def register_deployment(
    req: DeploymentRegisterRequest,
    request: Request,
) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-deployments-register:{identity}", admin_rate_limit)
    try:
        artifact = deployment_artifact_validator.validate(req.variant)
        deployment = Deployment(
            variant=req.variant,
            capabilities=set(req.capabilities),
            generation=req.generation,
            metadata={
                "gguf_architecture": artifact.architecture,
                "gguf_context_length": artifact.context_length,
                "gguf_embedding_length": artifact.embedding_length,
                "gguf_block_count": artifact.block_count,
                "gguf_file_type": artifact.file_type,
                "gguf_tensor_count": artifact.tensor_count,
                "gguf_fingerprint": deployment_artifact_validator.artifact_fingerprint(
                    artifact
                ),
            },
        )
        deployment_store.mutate(deployment_registry, lambda registry: registry.add(deployment))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/deployments/register",
        outcome="registered",
        identity_hash=identity,
        aggregate_id=deployment.variant_id,
    )
    return {
        "variant_id": str(deployment.variant_id),
        "state": deployment.state.value,
        "generation": deployment.generation,
        "artifact_sha256": artifact.sha256,
        "architecture": artifact.architecture,
        "context_length": artifact.context_length,
    }


@app.post("/hydra/v1/admin/deployments/{variant_id}/shadow")
async def begin_deployment_shadow(variant_id: UUID, request: Request) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-deployment-shadow:{identity}", admin_rate_limit)
    if str(variant_id) not in deployment_registry.deployments:
        raise HTTPException(status_code=404, detail="Deployment not found")

    def shadow(registry):
        deployment = registry.deployments[str(variant_id)]
        deployment_controller.begin_shadow(deployment)
        return deployment

    try:
        deployment = await asyncio.to_thread(deployment_store.mutate, deployment_registry, shadow)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/deployments/shadow",
        outcome="shadow",
        identity_hash=identity,
        aggregate_id=variant_id,
    )
    return {"variant_id": str(variant_id), "state": deployment.state.value}


@app.post("/hydra/v1/admin/deployments/{variant_id}/canary")
async def approve_deployment_canary(variant_id: UUID, request: Request) -> dict:
    """Promote SHADOW -> CANARY on the shadow evidence the server measured from live traffic."""
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-deployment-canary:{identity}", admin_rate_limit)
    if str(variant_id) not in deployment_registry.deployments:
        raise HTTPException(status_code=404, detail="Deployment not found")

    def canary(registry):
        deployment = registry.deployments[str(variant_id)]
        return deployment, deployment_controller.approve_canary(deployment)

    try:
        # Evidence aggregation reads the traffic log: keep it off the event loop.
        deployment, evidence = await asyncio.to_thread(deployment_store.mutate, deployment_registry, canary)
    except EvidenceRejected as exc:
        raise HTTPException(status_code=409, detail=_rejection(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/deployments/canary",
        outcome="canary",
        identity_hash=identity,
        aggregate_id=variant_id,
    )
    return {"variant_id": str(variant_id), "state": deployment.state.value, "evidence": asdict(evidence)}


@app.post("/hydra/v1/admin/deployments/{variant_id}/activate")
async def activate_deployment(variant_id: UUID, request: Request) -> dict:
    """Promote CANARY -> ACTIVE on the canary evidence the server measured from live traffic."""
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-deployment-activate:{identity}", admin_rate_limit)
    if str(variant_id) not in deployment_registry.deployments:
        raise HTTPException(status_code=404, detail="Deployment not found")

    def activate(registry):
        deployment = registry.deployments[str(variant_id)]
        evidence = deployment_controller.measure_canary(deployment)
        return deployment_controller.activate(deployment, evidence), evidence

    try:
        active, evidence = await asyncio.to_thread(deployment_store.mutate, deployment_registry, activate)
    except EvidenceRejected as exc:
        raise HTTPException(status_code=409, detail=_rejection(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/deployments/activate",
        outcome="active",
        identity_hash=identity,
        aggregate_id=variant_id,
    )
    return {"variant_id": str(active.variant_id), "state": active.state.value, "evidence": asdict(evidence)}


@app.get("/hydra/v1/admin/deployments/{variant_id}/evidence")
async def deployment_evidence(variant_id: UUID, request: Request) -> dict:
    """Live-traffic evidence for the deployment's current phase and the policy it must meet."""
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-deployment-evidence:{identity}", admin_rate_limit)
    deployment = deployment_registry.deployments.get(str(variant_id))
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    measured = None
    if deployment.state.value == "shadow":
        measured = asdict(await asyncio.to_thread(deployment_controller.measure_shadow, deployment))
    elif deployment.state.value == "canary":
        measured = asdict(await asyncio.to_thread(deployment_controller.measure_canary, deployment))
    return {
        "variant_id": str(variant_id),
        "state": deployment.state.value,
        "evidence": measured,
        "policy": asdict(deployment_controller.policy),
    }


def _rejection(exc: EvidenceRejected) -> dict:
    return {
        "error": str(exc),
        "evidence": asdict(exc.evidence),
        "policy": asdict(deployment_controller.policy),
    }


@app.post("/hydra/v1/admin/deployments/rollback/{capability}")
async def rollback_deployment(capability: str, request: Request) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-deployment-rollback:{identity}", admin_rate_limit)
    try:
        restored = await asyncio.to_thread(deployment_store.mutate, deployment_registry,
                                           lambda registry: registry.rollback(capability))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/deployments/rollback",
        outcome="rolled_back",
        identity_hash=identity,
        aggregate_id=restored.variant_id,
    )
    return {
        "variant_id": str(restored.variant_id),
        "state": restored.state.value,
        "capability": capability,
    }


@app.get("/hydra/v1/admin/outbox/dead-letters")
async def list_dead_letters(request: Request) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-dlq-list:{identity}", admin_rate_limit)
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/outbox/dead-letters",
        outcome="allowed",
        identity_hash=identity,
    )
    messages = capture_uow.outbox.dead_letters()
    return {
        "count": len(messages),
        "messages": [
            {
                "id": str(message.id),
                "topic": message.topic,
                "aggregate_id": str(message.aggregate_id),
                "trace_id": message.trace_id,
                "attempts": message.attempts,
                "last_error": message.last_error,
                "dead_lettered_at": message.dead_lettered_at,
            }
            for message in messages
        ],
    }


@app.post("/hydra/v1/admin/outbox/dead-letters/{message_id}/retry")
async def retry_dead_letter(message_id: UUID, request: Request) -> dict:
    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"admin-dlq-retry:{identity}", admin_rate_limit)
    requeued = capture_uow.outbox.requeue_dead_letter(message_id)
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/admin/outbox/dead-letters/retry",
        outcome="requeued" if requeued else "not_found",
        identity_hash=identity,
    )
    if not requeued:
        raise HTTPException(status_code=404, detail="Dead-letter message not found")
    return {"requeued": True, "message_id": str(message_id)}


@app.post("/hydra/v1/coding/verify-fix")
async def verify_code_fix(req: CodingRequest, request: Request) -> dict:
    """Generate and verify a patch in an expendable, container-tested workspace."""
    from uuid import uuid4

    identity = require_admin_access(request, security_config)
    rate_limiter.check(f"coding:{identity}", admin_rate_limit)
    security_audit.record(
        event_type="hydra.security.admin_access",
        endpoint="/hydra/v1/coding/verify-fix",
        outcome="allowed",
        identity_hash=identity,
    )

    task_id = uuid4()
    trace_id = uuid4().hex
    try:
        source = resolve_repository(settings.repositories_root, req.repository)
        agent = CodeAgent(
            llm,
            workspaces,
            artifacts,
            kernel.events,
            sandbox_factory=lambda root: OciSandbox(
                root,
                image=settings.sandbox_image,
                runtime=settings.sandbox_runtime,
            ),
            verification_policy=VerificationPolicy(
                VerificationMode(settings.code_verification_mode)
            ),
        )
        result = await agent.run(
            task_id=task_id,
            trace_id=trace_id,
            goal=req.goal,
            source=source,
            max_tokens=budget.output_tokens(req.max_tokens),
        )
        belief_id = None
        corpus_status = None
        if result.accepted:
            belief, corpus_record = learning.capture_verified_patch(
                task_id=task_id,
                artifacts=result.artifacts,
            )
            belief_id = str(belief.belief_id)
            corpus_status = corpus_record.status.value

        verification = None
        if result.verification is not None:
            verification = {
                "baseline_failed": result.verification.baseline_failed,
                "targeted_target": result.verification.targeted_target,
                "targeted_passed": result.verification.targeted_passed,
                "full_suite_passed": result.verification.full_suite_passed,
                "syntax_passed": result.verification.syntax_passed,
                "ruff_passed": result.verification.ruff_passed,
                "mypy_passed": result.verification.mypy_passed,
                "analysis_mode": result.verification.analysis_mode.value,
                "improvement_demonstrated": (
                    result.verification.improvement_demonstrated
                ),
                "verified": result.verification.verified,
            }

        replay_evidence = build_code_replay_evidence(
            task_id=task_id,
            result=result,
        )
        replay_manifest = replay_store.put(
            ReplayManifest(
                task_id=task_id,
                trace_id=trace_id,
                hydra_version=__version__,
                artifact_hashes=list(replay_evidence.artifact_hashes),
                event_types=[
                    "hydra.code.patch_verified"
                    if result.accepted
                    else "hydra.code.patch_rejected"
                ],
                verification_artifact_sha256=(
                    replay_evidence.verification_artifact_hash
                ),
                baseline_workspace_sha256=(
                    replay_evidence.baseline_workspace_sha256
                ),
                final_workspace_sha256=replay_evidence.final_workspace_sha256,
            )
        )

        provenance.append(
            ProvenanceRecord(
                task_id=task_id,
                trace_id=trace_id,
                action="coding.patch_verification",
                inputs={
                    "repository": req.repository,
                    "verification_mode": settings.code_verification_mode,
                },
                outputs={
                    "accepted": result.accepted,
                    "artifact_ids": [str(a.artifact_id) for a in result.artifacts],
                    "artifact_hashes": [a.sha256 for a in result.artifacts],
                    "verification": verification,
                    "replay_manifest_hash": replay_manifest.manifest_hash,
                },
            )
        )
        return {
            "task_id": str(task_id),
            "trace_id": trace_id,
            "accepted": result.accepted,
            "answer": result.answer,
            "artifact_ids": [str(a.artifact_id) for a in result.artifacts],
            "belief_id": belief_id,
            "corpus_status": corpus_status,
            "verification": verification,
            "replay_manifest_hash": replay_manifest.manifest_hash,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="HYDRA coding verification failed") from exc
