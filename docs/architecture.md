# Arquitectura de HYDRA 1.0

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Planos

| Plano | Paquetes |
|---|---|
| Cognitivo | `hydra.core` (kernel, contratos, máquina de estados, capture), `hydra.router`, `hydra.scheduler`, `hydra.workers`, `hydra.verification`, `hydra.meta`, `hydra.memory`, `hydra.world`, `hydra.planning`, `hydra.market` |
| Ejecución | `hydra.tools` (incl. workspace y tests estructurados), `hydra.cluster` (nodos, scheduler, fabric, capacidad), `hydra.providers`, `hydra.edge` |
| Aprendizaje | `hydra.corpus`, `hydra.training`, `hydra.model_factory`, `hydra.discovery`, `hydra.federated`, `hydra.lab`, `hydra.evals`, `hydra.replay` |
| IP y gobernanza | `hydra.ledger` (chain, signing, ip, licenses, bom, release), `hydra.governance` (security, boundary, secrets, policy_dsl, config_registry, redteam, invariants, recovery), `hydra.policy` |
| Interfaces | `hydra.api` (gateway, rutas OS y plataforma, Studio), `hydra.protocols` (MCP), `hydra.sdk`, `hydra.cli`, `sdk/typescript` |
| Observabilidad | `hydra.observability` (OTLP GenAI, flamegraph, costes, Prometheus), `hydra.telemetry` |

## Contratos estables

`hydra.core.task`: `HydraTask`, `HydraResult`, `EventEnvelope` (con `schema_version` y `payload_hash`),
`ContextFragment`, `SecurityContext`. Los servicios se comunican con estos contratos, eventos y APIs;
nunca con modelos internos de otro paquete.

## Almacenamiento

Local por defecto (`HYDRA_DATA_DIR`): `ledger/` (JSONL encadenado + anclas), `artifacts/` (CAS por sha256),
`world/` (log de deltas = versiones), `corpus/` (log versionado, linaje, tombstones, snapshots, releases),
`ip/`, `flight/`, `fabric/queue.db` (SQLite WAL), `planning/`, `training/`, `configs/`, `keys/`.
Multi-nodo: tablas equivalentes en `sql/schema.sql`, blobs en almacenamiento de objetos, bus NATS/Redis.

## Línea runtime (HYDRA-SO) integrada

`hydra.runtime` contiene la línea HYDRA-SO v0.4 (392 commits de historia, `git log --follow hydra/runtime/…`),
documentada en [docs/runtime/](runtime/). El mismo gateway (`hydra serve`) sirve sus rutas y ejecuta su outbox
transaccional; plan y decisiones en [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md).

| Pieza de la línea runtime | Dónde vive ahora | Estado |
|---|---|---|
| `rate_limit`, `circuit_breaker`, `language`, `hardware` | `governance.rate_limit`, `registry.circuit_breaker`, `hydra.language`, `edge.profiles` | Una implementación; `hydra.runtime.*` las reexporta |
| Límites de `workspaces` (symlinks, ficheros, bytes) | `tools.workspace.scan_source` | Adoptado por el WorkspaceManager de la plataforma |
| Patrones de `privacy` | `policy.kernel` + `corpus.gates.PrivacyGate` | Un único detector; `PrivacyScanner` delega en él |
| Límites de inspección de `gguf` | `model_factory.gguf` | Adoptados; `GGUFError` compartido |
| `gpu_telemetry` (pico de VRAM, falla cerrado) | backend de `edge.autobuild` | Adoptado |
| Presupuestos de `translation` | `edge.translation` + `/v1/translate` | Fusionado |
| `outbox`, `outbox_worker` | `core.capture_outbox` (reintentos del capture) + línea runtime | Adoptado |
| `code_verification` (criterios por capas) | `planning.runner.verification_report` | Adoptado por GoalRunner |
| `events`, `provenance` (cadenas hash) | anclados en `ledger` firmado (`ledger.runtime_anchor`) | Adaptador |
| `beliefs` | `world.runtime_beliefs` → World Model | Adaptador (se conserva el JSONL para replay) |
| `deployment*`, `promotion_gate` | `model_factory.deploy_bridge` (HYDRA.gguf → PROMOTED → despliegue) | Puente |
| `outbox_metrics` | `/metrics` (Prometheus) | Fusionado |
| `api` | `api.runtime_routes` (rutas montadas en el gateway) | Fusionado; la plataforma gana las colisiones |
| `kernel`, `router`, `planner`, `contracts`, `executor` | siguen en `hydra.runtime` | Sirven `/hydra/v1/tasks/route` y `/execute` (contrato estable) |

## Cadenas de suministro

Código, datos, modelos e IP siguen la misma disciplina: artefacto → evaluación → firma → linaje → gate
→ promoción. El grafo maestro PERSONA → CÓDIGO → EXPERIMENTO → DATOS → DATASET → MODELO → RESULTADO →
INVENCIÓN → PRODUCTO se reconstruye desde el ledger, el linaje del corpus y el del Model Factory.
