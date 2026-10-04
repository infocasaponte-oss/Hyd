# Roadmap

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

## v0.4.0-dev — Cognitive Runtime Hardening

Implemented in the current development line:

- typed task contracts and task state machine
- deterministic capability router and planner
- physical model deployment lifecycle with shadow/canary/rollback
- health-aware runtime routing and circuit breakers
- RTX 3060 Ti Model Factory/AutoQuant contracts and measured-vs-planned gates
- transactional SQLite outbox with retries, dead-letter queue and startup recovery
- hash-chained Event Store and Provenance verification
- replay manifests with physical model and coding-verification identity
- API liveness/readiness separation
- API/admin token policy and rate limiting
- protected dead-letter administration
- bounded workspaces with symlink/file/byte limits
- HYDRA sandbox image contract with preflight
- CodeAgent bounded source context
- patch-policy hardening
- layered coding verification: failing baseline, targeted test, full suite and syntax check
- conservative corpus rights gate and persistent exact deduplication
- dataset manifest factory

Still pre-alpha / not production-ready:

- replace local SQLite/JSONL stores with durable multi-process storage
- inter-process/file locking and transactional event materialization
- immutable/signed container and model artifact digests
- real GPU CI/benchmark execution on an RTX 3060 Ti
- broader HYDRA-E2E evaluation suite
- authentication suitable for multi-user deployments
- persistent distributed rate limiting
- full World Model / Belief Graph
- full memory compiler and hybrid retrieval
- production secrets broker
- multi-node GPU scheduler
- signed IP/license ledger and release gate

## v0.4.x — Verification and Operating Plane

- targeted test selection improvements
- static/type analysis adapters
- richer replay executor
- operational metrics and tracing
- persistent deployment evidence
- runtime/model lifecycle API

## v0.5 — Learning Plane

- memory compiler
- semantic/episodic/procedural stores
- richer corpus quality tiers and privacy scanning
- SFT/preference/process dataset compilers
- evaluation contamination guard
- model/dataset release attestations

## v0.6+

- capability discovery
- Cognitive JIT specialists
- GPU-aware distributed scheduler
- multimodal/VLM
- private/federated learning
