# HYDRA Deployment Lifecycle

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

Model quality promotion and production deployment are separate decisions.

PROMOTED -> CANDIDATE -> SHADOW -> CANARY -> ACTIVE -> DEPRECATED -> RETIRED

A candidate cannot skip directly to ACTIVE.

Shadow compares the candidate against the currently active path without making it authoritative. Advancement requires a minimum sample count, agreement threshold and error-rate ceiling.

Canary makes the candidate eligible for a limited production path. Activation requires a minimum request count plus error-rate and p95-latency gates.

When a new generation becomes ACTIVE, the overlapping previous generation becomes DEPRECATED rather than being deleted. HYDRA can therefore roll back to the latest compatible prior generation.

## Measured evidence (HYDRA 1.1)

Promotion evidence is measured by the server, never supplied by the operator:

* Every routed request appends a record to `runtime/runtime-evidence.jsonl` (`HYDRA_RUNTIME_DIR`):
  primary/shadow/canary variant, output hashes, exact agreement, per-call errors and latencies.
  A failed canary call is recorded as a canary error even though the active variant answers.
* Entering SHADOW or CANARY stores the current end of that log in the deployment metadata
  (`*_evidence_offset`); only records written afterwards count for that phase.
* `POST /hydra/v1/admin/deployments/{id}/canary` and `/activate` take no body: they measure, apply
  `DeploymentPolicy` and answer with the evidence used, or `409` with the evidence and the policy.
* `GET /hydra/v1/admin/deployments/{id}/evidence` shows the live evidence of the current phase and
  the thresholds it must reach.

Agreement is exact output equality, so shadow comparisons are meaningful with deterministic
sampling (temperature 0, fixed seed).
