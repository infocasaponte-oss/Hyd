# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Runtime settings, read from environment variables (prefix HYDRA_)."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hydra.tools.sandbox import DEFAULT_SANDBOX_IMAGE

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
# Source checkout -> repository root; installed package -> current directory.
_INSTALLED_ROOT = Path(sys.prefix) / "share" / "hydra"
ROOT = (_SOURCE_ROOT if (_SOURCE_ROOT / "config").is_dir() else
        _INSTALLED_ROOT if (_INSTALLED_ROOT / "config").is_dir() else Path.cwd())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HYDRA_", env_file=".env", extra="ignore")

    models_config: Path = ROOT / "config" / "models.yaml"
    evaluation_candidate_version: int = Field(default=5, ge=5, le=8)
    policy_config: Path = ROOT / "config" / "policy.yaml"
    evals_dir: Path = ROOT / "config" / "evals"
    data_dir: Path = Path.cwd() / "data"
    """Local state: failure memory, lab experiments, model factory store."""

    # Infrastructure. Empty value -> in-memory implementation.
    postgres_url: str = ""
    redis_url: str = ""

    # Runtimes
    vllm_base_url: str = "http://localhost:8000/v1"
    ollama_base_url: str = "http://localhost:11434"
    llamacpp_base_url: str = "http://localhost:8081/v1"
    cloud_base_url: str = "https://api.openai.com/v1"
    cloud_api_key: str = ""
    internal_api_key: str = ""
    """Bearer token for internal OpenAI-compatible runtimes (vLLM/llama.cpp). Empty -> no header."""

    # Use deterministic offline models (no runtime needed). Great for dev/tests.
    offline: bool = False

    # Sandbox: "docker" (isolated container) or "subprocess" (dev only).
    sandbox_backend: str = "docker"
    sandbox_image: str = DEFAULT_SANDBOX_IMAGE
    workspace_dir: Path = Path.cwd() / "workspace"
    # Mount source for the sandbox as seen by the Docker daemon (e.g. a named volume
    # when HYDRA itself runs in a container). Empty -> workspace_dir.
    sandbox_workspace_source: str = ""

    # Optional System-One routing classifier (a model id from the registry).
    router_model: str = ""
    # Hyd replaces the external decision sidecar with HYDRA-owned local inference.
    hyd_enabled: bool = True
    hyd_model_path: Path = ROOT / "config" / "hyd" / "model.json"
    hyd_calibration_path: Path = ROOT / "config" / "hyd" / "calibration.json"
    hyd_authority_evidence_path: Path | None = None
    # Experimental local typed decisions: disabled until explicitly configured.
    decision_shadow_endpoint: str = ""
    decision_shadow_model: str = "hyd-latest"
    decision_full_contract: bool = False
    decision_shadow_timeout_s: float = Field(default=0.5, gt=0, le=5)
    decision_calibrator_path: Path | None = None
    decision_local_model_path: Path | None = None
    decision_local_calibration_path: Path | None = None
    decision_authority_evidence_path: Path | None = None
    # Embeddings: "hashing" (local, no model) | "vllm" | "ollama" (e.g. nomic-embed-text).
    embedding_provider: str = "hashing"
    embedding_model: str = ""
    # Domains research workers may fetch from (comma separated). Empty -> built-in list.
    network_domains: str = ""
    public_web_enabled: bool = False

    repositories_root: Path = Path.cwd() / "repositories"
    """API clients may only point goals and code graphs at directories below this root
    (HYDRA_REPOSITORIES_ROOT, shared with the runtime coding route)."""

    # Gateway protection. Empty -> no auth (development).
    api_key: str = Field(default="", validation_alias=AliasChoices("api_key", "HYDRA_API_KEY", "HYDRA_API_TOKEN"))
    """Gateway token (HYDRA_API_KEY, or HYDRA_API_TOKEN as used by the runtime line)."""
    admin_token: str = ""
    client_keys_file: Path = Path("data/keys/api-clients.json")
    """HYDRA_ADMIN_TOKEN: required (header ``X-Hydra-Admin-Token``) by routes that change governance,
    IP, corpus approval, releases, models or sync state. Empty -> those routes accept loopback only."""
    sync_trusted_keys_dir: Path | None = None
    """Directory with ``*.pub.pem`` keys trusted for edge sync imports (default: <data_dir>/keys/trusted).
    This node's own public key is always trusted; clients can never supply keys."""
    fabric_backend: str = "auto"
    """HYDRA_FABRIC_BACKEND: execution-fabric queue: auto (PostgreSQL when HYDRA_POSTGRES_URL is set and
    psycopg is installed, else local SQLite) | sqlite | postgres (required: fail if unavailable)."""
    ledger_backend: str = "auto"
    """HYDRA_LEDGER_BACKEND: signed IP/provenance ledger: auto (PostgreSQL when HYDRA_POSTGRES_URL is set and
    psycopg is installed, else data/ledger files) | file | postgres (required). A PostgreSQL ledger adopts an
    existing file ledger once, after verifying it; the file is kept as a read-only copy."""
    corpus_backend: str = "auto"
    """HYDRA_CORPUS_BACKEND: corpus logs (records, lineage, tombstones, snapshots): auto (PostgreSQL table
    hydra_logs when HYDRA_POSTGRES_URL is set and psycopg is installed, else data/corpus files) | file |
    postgres (required). Existing files are imported once and kept as a read-only copy."""
    world_backend: str = "auto"
    """HYDRA_WORLD_BACKEND: World Model delta log and snapshots: auto (PostgreSQL table hydra_logs when
    HYDRA_POSTGRES_URL is set and psycopg is installed, else data/world files) | file | postgres (required).
    Existing files are imported once and kept as a read-only copy."""
    ip_backend: str = "auto"
    """HYDRA_IP_BACKEND: invention registry log: auto (PostgreSQL stream ip/inventions.jsonl of hydra_logs when
    HYDRA_POSTGRES_URL is set and psycopg is installed, else data/ip files) | file | postgres (required)."""
    artifacts_backend: str = "auto"
    """HYDRA_ARTIFACTS_BACKEND: artifact manifest log: auto (PostgreSQL stream artifacts/manifests.jsonl of
    hydra_logs when HYDRA_POSTGRES_URL is set and psycopg is installed, else data/artifacts files) | file |
    postgres (required)."""
    artifact_objects: str = ""
    """HYDRA_ARTIFACT_OBJECTS: where artifact blobs live: empty (data/artifacts/objects), a directory (e.g. a
    volume every node mounts) or s3://bucket/prefix (needs the s3 extra; credentials from the AWS variables)."""
    s3_endpoint_url: str = ""
    """HYDRA_S3_ENDPOINT_URL: S3-compatible endpoint (MinIO, Ceph, R2...); empty for AWS S3."""
    require_shared_state: bool = False
    """HYDRA_REQUIRE_SHARED_STATE: refuse to start unless every plane is on shared storage (PostgreSQL) and
    the private keys are outside the data directory. Set it wherever more than one replica runs: a
    misconfigured node then fails fast instead of writing local files that the others never see."""
    documents_backend: str = "auto"
    """HYDRA_DOCUMENTS_BACKEND: small shared registries of the engine and the factory (feature flags,
    config sets, secret vault and policies, lab, glossaries, model lifecycle, factory registry and
    adapters, failure memory, edge sync state): auto (PostgreSQL table hydra_documents and hydra_logs when
    HYDRA_POSTGRES_URL is set and psycopg is installed, else their files under HYDRA_DATA_DIR) | file |
    postgres (required). Existing files are adopted once and kept."""
    key_backend: str = "auto"
    """HYDRA_KEY_BACKEND: where private keys live (hydra.core.keystore): auto | keyring | file | legacy."""
    keys_dir: Path | None = None
    """HYDRA_KEYS_DIR: key files outside HYDRA_DATA_DIR (mounted secrets), used when no OS keyring."""
    key_namespace: str = ""
    """HYDRA_KEY_NAMESPACE: keyring namespace (default: derived from the data directory path)."""

    @field_validator("sync_trusted_keys_dir", "keys_dir", mode="before")
    @classmethod
    def _empty_path_is_unset(cls, value):
        # An empty variable (HYDRA_SYNC_TRUSTED_KEYS_DIR= / HYDRA_KEYS_DIR=, as in .env.example) would
        # otherwise become Path('.'): the working directory would hold trusted or private keys.
        return None if isinstance(value, str) and not value.strip() else value

    api_rate_limit_per_minute: int = 60
    """Per-client limit for authenticated API routes. Set <= 0 to disable."""

    # Poll runtime metrics (vLLM/llama.cpp /metrics, Ollama /api/ps, nvidia-smi) for load-aware routing.
    runtime_monitor: bool = True
    monitor_interval_s: float = 5.0
    # NATS JetStream bus (takes precedence over Redis when set), e.g. nats://localhost:4222
    nats_url: str = ""
    # Model Factory toolchain: llama.cpp checkout/build dir (convert_hf_to_gguf.py, llama-quantize...).
    llamacpp_dir: str = ""

    # Stretch wall-clock budgets (local GPUs with cold model loads: 2-4).
    budget_time_scale: float = 1.0

    # ---- HYDRA 1.0 planes ----------------------------------------------------------
    policy_rules_config: Path = ROOT / "config" / "policy_rules.yaml"
    """Policy DSL rules (deny/review/allow)."""
    licenses_config: Path = ROOT / "config" / "licenses.yaml"
    """License profiles and registered component licenses."""
    capture: bool = True
    """Capture pipeline: world model, artifacts (CAS), corpus, ledger, flight recorder."""
    capture_outbox_poll_s: float = 2.0
    outbox_backend: str = "auto"
    """HYDRA_OUTBOX_BACKEND: capture outbox: auto (PostgreSQL table capture_outbox when HYDRA_POSTGRES_URL is
    set and psycopg is installed, else data/capture_outbox.db) | sqlite | postgres (required). Unpublished
    messages of an existing SQLite outbox are imported once."""
    """How often deferred capture writes (ledger/corpus) are retried from the outbox."""
    corpus_auto_training_max_sensitivity: int = 0
    """Own executions at or below this sensitivity are trainable by default (0 = PUBLIC)."""
    deterministic_first: bool = False
    """Answer with deterministic solvers (calculator, sympy, JSON/SQL validators) when certain."""
    ledger_anchor_every: int = 1000
    node_id: str = ""
    """Cluster node id (default: hostname)."""
    cluster_rerank: bool = True
    """Re-rank models by cluster placement (residency, KV locality, queue, SLA) when nodes report."""
    heartbeat_interval_s: float = 15.0
    otel_endpoint: str = ""
    """OTLP/HTTP traces endpoint (e.g. http://localhost:4318). Empty -> in-process spans only."""
    llama_server: str = ""
    """Path to llama-server for the AutoBuilder (default: search PATH / HYDRA_LLAMACPP_DIR)."""

    # Request budgets shared with the runtime line (HYDRA_MAX_INPUT_CHARS, HYDRA_MAX_TRANSLATION_CHUNKS).
    max_input_chars: int = 50_000
    max_translation_chunks: int = 64

    runtime_api: bool = True
    """Serve the HYDRA-SO runtime line (/ready, /v1/chat, /hydra/v1/admin/*, coding) from the gateway."""
    runtime_anchor_interval_s: float = 300.0
    """Anchor the runtime event/provenance chain heads in the signed ledger this often (0 = only on shutdown)."""

    # Runtime line (hydra.core.native_config.Settings is a view of these; same HYDRA_* variables as before).
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    llm_url: str = "http://127.0.0.1:8081/v1"
    """HYDRA_LLM_URL: OpenAI-compatible server the runtime line chats with (llama-server)."""
    models_dir: str = "models"
    """HYDRA_MODELS_DIR: GGUF models the runtime line inventories and deploys."""
    runtime_dir: str = "runtime"
    """HYDRA_RUNTIME_DIR: runtime-line state (events, provenance, outbox, deployments...)."""
    runtime_db: str = ""
    """HYDRA_RUNTIME_DB: runtime-line SQLite database (default <runtime_dir>/hydra.db)."""
    deployments_file: str = ""
    """HYDRA_DEPLOYMENTS_FILE: deployment registry (default <runtime_dir>/deployments.json)."""
    readiness_max_pending: int = 1000
    readiness_max_pending_age_seconds: float = 300.0
    admin_rate_limit_per_minute: int = 6
    sandbox_runtime: str = "docker"
    code_verification_mode: str = "advisory"
    workspace_max_files: int = 20_000
    workspace_max_bytes: int = 256 * 1024 * 1024
    max_output_tokens: int = 4096
    runtime_backend: str = "auto"
    """HYDRA_RUNTIME_BACKEND: runtime-line state (event and provenance hash chains, live-traffic evidence,
    deployment registry, and the hydra.db stores: outbox, task commits, metrics, health, promotion evidence): auto (PostgreSQL streams
    runtime/* of hydra_logs when HYDRA_POSTGRES_URL is set and psycopg is installed, else files under
    HYDRA_RUNTIME_DIR) | file | postgres (required). Existing files are imported once and kept."""

    hedge_after_ms: float = 3500
    breaker_failures: int = 5
    breaker_cooldown_s: float = 60
