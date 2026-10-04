# HYDRA Runtime v0.3.1

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

> **Documento histórico de HYDRA-SO v0.4.** Esta línea se integró en HYDRA 1.1 como `hydra.runtime` (PR #13). Las instrucciones de instalación, la versión de Python, el estado *pre-alpha* y la forma de arrancar que aparezcan aquí ya no aplican: consulta el [README](../../README.md), la [arquitectura](../architecture.md) y la [política de seguridad](../../SECURITY.md).

## Local development

HYDRA deliberately binds its API to localhost during pre-alpha.

1. Start a local OpenAI-compatible `llama-server` on port 8081.
2. Put GGUF artifacts under `models/`.
3. Start HYDRA:

```bash
./scripts/run_api.sh
```

## Gateway endpoints

- `GET /health`
- `POST /v1/chat`
- `POST /v1/translate`
- `PUT /v1/glossaries/{id}`
- `GET /v1/models`

## Runtime safety

The API does not accept arbitrary model-directory paths. Model inventory is confined to the configured models root, and only relative paths are returned.

Request budgets limit input characters, generated-token requests and translation chunks. These are engineering safeguards, not a complete production security boundary.
