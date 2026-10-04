# Security Policy

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

HYDRA is currently pre-alpha.

## Current constraints

- Bind development services to localhost.
- Do not expose llama.cpp/vLLM directly to the public Internet.
- Never commit credentials, model-provider tokens or private datasets.
- Do not execute generated code on the host; the planned Tool Runtime must use isolated sandboxes.
- Treat downloaded model weights and datasets as untrusted artifacts until verified.

## Reporting

Use the repository's private security reporting mechanism when enabled. Do not publish secrets or exploitable vulnerabilities in public issues.
