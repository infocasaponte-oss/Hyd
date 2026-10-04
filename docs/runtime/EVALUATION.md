# HYDRA Evaluation and Promotion

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

Performance never overrides correctness.

A physical model variant must pass:
- artifact and lineage integrity;
- benchmark execution;
- minimum quality score;
- TTFT ceiling;
- minimum generation throughput;
- hardware memory gate;
- explicit promotion.

The initial RTX 3060 Ti suite is intentionally small and is not a claim of broad model quality. It establishes the versioned evaluation contract. Future suites will expand to coding, tool use, multilingual translation, structured output, contradiction handling, recovery and policy tests.

Every benchmark suite has a stable ID, version and content hash so a promotion can name the exact evaluation definition used.
