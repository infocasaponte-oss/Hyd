# HYDRA-SO

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

**HYDRA** es un sistema operativo cognitivo híbrido orientado a orquestar modelos locales/cloud, herramientas, memoria, verificación, corpus de entrenamiento y trazabilidad de modelos/datos/IP.

> Estado: **pre-alpha / research & engineering prototype**.

## Primer objetivo de hardware

La implementación inicial está diseñada para una **NVIDIA GeForce RTX 3060 Ti (8 GB)** usando `llama.cpp` + CUDA y modelos GGUF cuantizados.

## Capacidades iniciales

- inferencia local OpenAI-compatible;
- routing por capacidades;
- traducción multilingüe;
- perfiles automáticos de hardware;
- selección/benchmark de runtime;
- Model Scout para GGUF;
- ejecución verificable y event sourcing (roadmap);
- Corpus Engine y provenance/IP ledger (roadmap);
- Model Factory / Cognitive JIT (roadmap).

## Arquitectura

```text
Input/API
   |
Gateway
   |
Cognitive Kernel
   +-- Router / Planner / Scheduler
   +-- Models / Tools / Memory
   +-- Verifier / Belief State
   |
Capture
   +-- Corpus
   +-- Telemetry
   +-- Provenance / IP
   |
Model Factory / Training Lab
```

## Seguridad

No expongas `llama-server` directamente a Internet. El prototipo debe permanecer ligado a localhost hasta incorporar autenticación, rate limiting, sandboxing y Policy Engine.

## Desarrollo

Requiere Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## Estado del proyecto

La primera rama de desarrollo construirá **HYDRA Runtime v0.3.1 (Audit Hardening)** y posteriormente el Cognitive Kernel.

Consulta [ROADMAP.md](ROADMAP.md) y [ARCHITECTURE.md](ARCHITECTURE.md).
