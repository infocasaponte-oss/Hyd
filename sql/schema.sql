-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
-- HYDRA Cognitive Engine - PostgreSQL schema (idempotent).

CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL,
    request         JSONB NOT NULL,
    route           JSONB,
    final_response  JSONB
);

CREATE TABLE IF NOT EXISTS events (
    id          UUID PRIMARY KEY,
    task_id     UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    payload     JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS events_task_idx ON events (task_id, created_at);

CREATE TABLE IF NOT EXISTS memories (
    id                UUID PRIMARY KEY,
    memory_type       TEXT NOT NULL,
    content           JSONB NOT NULL,
    text              TEXT NOT NULL,
    confidence        DOUBLE PRECISION,
    status            TEXT NOT NULL DEFAULT 'unverified',
    importance        DOUBLE PRECISION,
    embedding         DOUBLE PRECISION[],
    conflicts_with    UUID[] NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL,
    last_accessed_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS memories_type_idx ON memories (memory_type, created_at DESC);

CREATE TABLE IF NOT EXISTS inference_runs (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL,
    task_id         UUID NOT NULL,
    task_type       TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    role            TEXT NOT NULL,
    latency_ms      DOUBLE PRECISION,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    success         BOOLEAN,
    verifier_score  DOUBLE PRECISION,
    user_feedback   DOUBLE PRECISION,
    complexity      DOUBLE PRECISION,
    mode            TEXT,
    arm             TEXT,
    task_confidence DOUBLE PRECISION
);
ALTER TABLE inference_runs ADD COLUMN IF NOT EXISTS complexity DOUBLE PRECISION;
ALTER TABLE inference_runs ADD COLUMN IF NOT EXISTS mode TEXT;
ALTER TABLE inference_runs ADD COLUMN IF NOT EXISTS arm TEXT;
ALTER TABLE inference_runs ADD COLUMN IF NOT EXISTS task_confidence DOUBLE PRECISION;
CREATE INDEX IF NOT EXISTS inference_runs_model_idx ON inference_runs (model_id, task_type);
CREATE INDEX IF NOT EXISTS inference_runs_task_idx ON inference_runs (task_id);

CREATE TABLE IF NOT EXISTS model_metrics (
    model_id        TEXT NOT NULL,
    task_type       TEXT NOT NULL,
    runs            INTEGER NOT NULL,
    success_rate    DOUBLE PRECISION,
    avg_latency_ms  DOUBLE PRECISION,
    avg_quality     DOUBLE PRECISION,
    PRIMARY KEY (model_id, task_type)
);


-- =====================================================================================
-- Execution Fabric (hydra.cluster.fabric_pg.PostgresWorkQueue, which also creates these tables).
-- Shared by every gateway and worker: leases, retries, dead letters, idempotency, checkpoints.
-- =====================================================================================
CREATE TABLE IF NOT EXISTS fabric_work (
    id            TEXT PRIMARY KEY,
    capability    TEXT NOT NULL,
    priority      INTEGER NOT NULL,
    status        TEXT NOT NULL,
    available_at  DOUBLE PRECISION NOT NULL,
    lease_expires DOUBLE PRECISION,
    idem          TEXT NOT NULL,
    body          JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS fabric_work_claim ON fabric_work (status, capability, priority, available_at);
CREATE INDEX IF NOT EXISTS fabric_work_open_idem ON fabric_work (idem) WHERE status IN ('queued', 'leased');
CREATE TABLE IF NOT EXISTS fabric_idempotency (
    key    TEXT PRIMARY KEY,
    result JSONB NOT NULL,
    at     DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS fabric_checkpoints (
    task_id TEXT NOT NULL,
    step    INTEGER NOT NULL,
    state   JSONB NOT NULL,
    at      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (task_id, step)
);


-- =====================================================================================
-- Signed IP / provenance ledger: hydra.ledger.pg.PostgresLedger (HYDRA_LEDGER_BACKEND), which
-- also creates these tables. Append-only: triggers reject UPDATE, DELETE and TRUNCATE.
-- =====================================================================================
CREATE TABLE IF NOT EXISTS ip_events (
    sequence_id        BIGSERIAL PRIMARY KEY,
    event_id           UUID NOT NULL UNIQUE,
    project_id         TEXT NOT NULL DEFAULT 'hydra',
    event_type         TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL,
    actor_type         TEXT NOT NULL,
    actor_id           TEXT NOT NULL,
    object_type        TEXT NOT NULL DEFAULT '',
    object_id          TEXT NOT NULL DEFAULT '',
    payload            JSONB NOT NULL,
    previous_hash      TEXT,
    event_hash         TEXT NOT NULL,
    signature          TEXT,
    signing_key_id     TEXT,
    confidentiality    TEXT NOT NULL,
    created_by_service TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ip_events_object ON ip_events (object_type, object_id);

CREATE OR REPLACE FUNCTION hydra_ledger_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ip_events is append-only: use an EVENT_CORRECTION event';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ip_events_no_update ON ip_events;
CREATE TRIGGER ip_events_no_update BEFORE UPDATE OR DELETE ON ip_events
    FOR EACH ROW EXECUTE FUNCTION hydra_ledger_immutable();
DROP TRIGGER IF EXISTS ip_events_no_truncate ON ip_events;
CREATE TRIGGER ip_events_no_truncate BEFORE TRUNCATE ON ip_events
    FOR EACH STATEMENT EXECUTE FUNCTION hydra_ledger_immutable();
-- Exact serialized event (what verification recomputes; TIMESTAMPTZ/JSONB are for querying).
ALTER TABLE ip_events ADD COLUMN IF NOT EXISTS body TEXT;
CREATE INDEX IF NOT EXISTS ip_events_type ON ip_events (event_type, sequence_id);

CREATE TABLE IF NOT EXISTS ledger_anchors (
    first_sequence   BIGINT NOT NULL,
    last_sequence    BIGINT NOT NULL,
    merkle_root      TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    external_timestamp_ref TEXT,
    PRIMARY KEY (first_sequence, last_sequence)
);
ALTER TABLE ledger_anchors ADD COLUMN IF NOT EXISTS body TEXT;

-- =====================================================================================
-- Event logs of the event-sourced planes: hydra.core.eventlog (HYDRA_CORPUS_BACKEND, HYDRA_WORLD_BACKEND,
-- HYDRA_IP_BACKEND, HYDRA_ARTIFACTS_BACKEND),
-- which also creates this table. One stream per log file (``corpus/log.jsonl``, ``world/deltas.jsonl``...),
-- gap-free ``seq`` per stream,
-- exact JSON line in ``body``. Append-only: triggers reject UPDATE, DELETE and TRUNCATE.
-- =====================================================================================
CREATE TABLE IF NOT EXISTS hydra_logs (
    stream     TEXT NOT NULL,
    seq        BIGINT NOT NULL,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (stream, seq)
);
CREATE OR REPLACE FUNCTION hydra_logs_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'hydra_logs is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS hydra_logs_no_update ON hydra_logs;
CREATE TRIGGER hydra_logs_no_update BEFORE UPDATE OR DELETE ON hydra_logs
    FOR EACH ROW EXECUTE FUNCTION hydra_logs_immutable();
DROP TRIGGER IF EXISTS hydra_logs_no_truncate ON hydra_logs;
CREATE TRIGGER hydra_logs_no_truncate BEFORE TRUNCATE ON hydra_logs
    FOR EACH STATEMENT EXECUTE FUNCTION hydra_logs_immutable();

-- =====================================================================================
-- Capture outbox: hydra.core.capture_outbox_pg.PostgresOutbox (HYDRA_OUTBOX_BACKEND), which also creates
-- it. Deferred ledger/corpus writes; workers claim due rows with FOR UPDATE SKIP LOCKED and a lease.
-- =====================================================================================
CREATE TABLE IF NOT EXISTS capture_outbox (
    id               UUID PRIMARY KEY,
    topic            TEXT NOT NULL,
    aggregate_id     UUID NOT NULL,
    trace_id         TEXT NOT NULL,
    payload          JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    published_at     TIMESTAMPTZ,
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ,
    last_error       TEXT,
    dead_lettered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS capture_outbox_due ON capture_outbox (next_attempt_at, created_at)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL;

-- =====================================================================================
-- Runtime line (hydra.runtime.pg_stores, HYDRA_RUNTIME_BACKEND), which also creates these tables
-- (runtime_outbox has the capture_outbox layout and is created by PostgresOutbox).
-- =====================================================================================
CREATE TABLE IF NOT EXISTS task_commits (
    task_id      UUID PRIMARY KEY,
    trace_id     TEXT NOT NULL,
    status       TEXT NOT NULL,
    result       JSONB NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS deployment_evidence (
    id         BIGSERIAL PRIMARY KEY,
    variant_id TEXT NOT NULL,
    phase      TEXT NOT NULL,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS deployment_evidence_variant_phase ON deployment_evidence (variant_id, phase, id);
CREATE TABLE IF NOT EXISTS operating_metrics (
    id          BIGSERIAL PRIMARY KEY,
    node        TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    payload     JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_spans (
    id          BIGSERIAL PRIMARY KEY,
    node        TEXT NOT NULL,
    span        JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS runtime_health (
    node              TEXT NOT NULL,
    variant_id        TEXT NOT NULL,
    state             TEXT NOT NULL,
    failures          INTEGER NOT NULL,
    failure_threshold INTEGER NOT NULL,
    recovery_seconds  DOUBLE PRECISION NOT NULL,
    opened_at_wall    DOUBLE PRECISION,
    updated_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (node, variant_id)
);

-- =====================================================================================
-- Shared documents: hydra.core.docstore (HYDRA_DOCUMENTS_BACKEND), which also creates the table. One
-- row per small registry (flags.json, models/jobs.json, secrets/vault...), changed by read-modify-write
-- under a row lock (SELECT ... FOR UPDATE); version bumps tell nodes to refresh their cache.
-- =====================================================================================
CREATE TABLE IF NOT EXISTS hydra_documents (
    name       TEXT PRIMARY KEY,
    body       JSONB NOT NULL,
    version    BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================================
-- Tables of earlier schema versions that were reserved and never written (safe to drop).
-- =====================================================================================
-- Artifact manifests live in hydra_logs (stream artifacts/manifests.jsonl); blobs in HYDRA_ARTIFACT_OBJECTS.
-- The reserved artifacts table was never written; it may be dropped.

-- The corpus lives in hydra_logs (streams corpus/*). The reserved corpus_records/corpus_lineage tables
-- of earlier schema versions were never written; databases that created them may drop them.

-- The invention registry lives in hydra_logs (stream ip/inventions.jsonl). The reserved inventions
-- table of earlier schema versions was never written; it may be dropped.

-- The World Model lives in hydra_logs (streams world/*). The reserved world_entities, world_relations,
-- beliefs and world_deltas tables of earlier schema versions were never written; they may be dropped.
