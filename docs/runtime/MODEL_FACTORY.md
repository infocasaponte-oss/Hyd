# HYDRA Model Factory

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

The Model Factory never treats a filename as proof that a model was built.

A promotable variant requires:
1. base-model identity and SHA-256;
2. dataset manifest identity/hash when training data was used;
3. a physical model artifact with SHA-256;
4. an explicit quantization;
5. measured benchmark results;
6. a passing hardware/quality gate.

## RTX 3060 Ti 8 GB initial search space

- quality: Q5_K_M, context 4096
- balanced: Q4_K_M, context 8192
- context: Q4_K_M, context 12288

All start with one parallel sequence, q8_0 K/V cache and maximum GPU-layer offload. These are candidates, not guaranteed-safe configurations. Actual promotion depends on measured VRAM, TTFT, throughput and quality.

## Benchmark correctness

TTFT is measured from request start to first streamed token. Generation throughput uses generated token counts and generation duration. Peak VRAM must come from the runtime/hardware monitor, not a before/after snapshot.

## llama.cpp builds

HYDRA generates argument vectors for conversion, quantization and serving. It does not mark an artifact converted/quantized merely because a command was planned. A supervisor must execute the command, verify exit status, verify the output exists, hash it, then advance build state.
