# Model Factory Runtime

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

The runtime closes several pre-alpha correctness gaps.

## BuildSupervisor

A conversion or quantization succeeds only if:
- the child process exits successfully;
- the expected output file exists;
- the file is non-empty;
- SHA-256 can be computed.

Planning a command never creates a model variant.

## ProcessSupervisor

HYDRA owns model-server child processes and performs terminate -> bounded wait -> kill fallback. This prevents normal shutdown paths from leaving unmanaged llama-server processes.

## GPU telemetry

Peak VRAM is sampled repeatedly with nvidia-smi while a workload runs. If NVIDIA telemetry is unavailable, HYDRA returns no samples rather than fabricating a measurement.

## Pareto selection

Candidates are compared on measured quality, throughput, TTFT and peak VRAM. A candidate is removed only when another candidate is no worse on every dimension and strictly better on at least one. Hardware-overflow and failed candidates never enter the frontier.
