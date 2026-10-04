# Política de seguridad

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Versiones con soporte

| Versión | Soporte de seguridad |
|---|---|
| 1.1.x (`main`) | Sí |
| 1.0.x y HYDRA-SO 0.4 (línea runtime anterior) | No: están integradas en 1.1 |

## Cómo informar de una vulnerabilidad

No abras un issue público. Usa el canal privado de GitHub: pestaña **Security → Report a vulnerability** de
este repositorio (*private vulnerability reporting*). Incluye:

- componente y versión (o commit);
- pasos para reproducirlo y su impacto;
- si es posible, una prueba de concepto mínima.

Se confirma la recepción y se coordina la corrección y la publicación del aviso antes de divulgar detalles.

## Qué cubre

- El gateway HTTP (`hydra serve`), incluidas las rutas de la línea runtime (`/hydra/v1/admin/*`, `/hydra/v1/coding/*`).
- Aislamiento de ejecución: sandbox OCI, workspaces y aplicación de parches.
- Tratamiento de secretos, privacidad del corpus, ledger firmado y cadenas de evidencia.
- Importación de modelos: GGUF, safetensors y firmas.

## Postura por defecto

- Sin `HYDRA_API_KEY`/`HYDRA_API_TOKEN` el gateway solo atiende peticiones locales.
- Las rutas de administración exigen `HYDRA_ADMIN_TOKEN` y fallan cerradas sin él.
- Las rutas que reciben rutas de fichero las limitan a `HYDRA_REPOSITORIES_ROOT`.
- `python.test` nunca ejecuta código en el host.
- Los errores internos no se devuelven a los clientes.

No expongas los runtimes de modelos (llama-server, vLLM, Ollama) directamente a Internet: solo el gateway
debe hablar con ellos. Modelo de amenazas y controles en [docs/security.md](docs/security.md).
