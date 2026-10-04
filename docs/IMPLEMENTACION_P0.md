# Implementación P0: aislamiento y preparación CUDA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Continúa `PLAN_IMPLEMENTACION_MOTOR_PROPIO.md` desde `2087bcd`. Estado: aislamiento implementado y verificado; preparación CUDA en curso. P0 no está completamente cerrada ni se ha ejecutado el resto del plan.

## Aislamiento de python.test

`ToolRuntime` admite un `OciSandbox` explícito cuyo workspace debe coincidir. La autorización de ejecución sigue siendo obligatoria. Sin sandbox se mantiene el fallo cerrado: no hay fallback al host. Con sandbox ejecuta pytest en Docker sin red, usuario no root, capacidades eliminadas, límites de memoria/CPU/PIDs y montaje de proyecto de solo lectura. No se ha activado implícitamente esta herramienta en todas las rutas del motor.

El comando normaliza rutas para el contenedor, evita tratar nombres que empiezan por guion como opciones de pytest y desactiva la escritura de caché. Cada ejecución tiene un nombre único. Ante timeout o cancelación se detiene el cliente y se intenta eliminar ese contenedor concreto con un plazo limitado; si el daemon está indisponible, la limpieza no puede garantizarse y debe comprobarse operativamente.

Evidencia real con la imagen local `hydra-sandbox:py312-v3`:

- Código ejecutado como usuario no privilegiado; variable de prueba del host ausente; escritura en proyecto denegada; ningún archivo creado en host. `docs/evidence/p0-isolation.json`.
- Prueba que duerme 30 s limitada a 3 s: código 124; después, `docker ps -a --filter name=hydra-test-` no mostró contenedores. `docs/evidence/p0-timeout.json`.
- Suite completa: **413 passed, 5 skipped**, 158,10 s. Ruff correcto. Regresiones de autorización, ruta, workspace, timeout y cancelación cubiertas.

El sandbox histórico de CodeAgent conserva su modo de montaje anterior para no alterar su flujo de trabajo; el montaje de solo lectura se exige específicamente en la nueva vía `ToolRuntime/python.test`.

## CUDA en Kev

La instalación aislada existente era `torch 2.8.0+cpu`. Se seleccionó la distribución oficial Windows/Python 3.12 de `torch 2.8.0+cu128`, compatible con la restricción de versión del checkout Kev. Fuente: [versiones oficiales de PyTorch](https://pytorch.org/get-started/previous-versions/).

`scripts/prepare_kev_cuda.ps1` descarga de forma reanudable, valida tamaño y SHA256 publicado en el índice oficial, instala solo el wheel en `runtime/kev-env`, ejecuta `pip check` y comprueba un tensor en GPU. Guarda estado en `runtime/kev-cuda-status.json` y evidencia solo si el cálculo termina correctamente en `runtime/kev-cuda-evidence.json`. El bloqueo de archivo evita preparaciones simultáneas. Un error produce FAILED y conserva el parcial.

Wheel: 3.461.384.651 bytes. SHA256: `0ad925202387f4e7314302a1b4f8860fa824357f9b1466d7992bf276370ebcff`. La primera descarga por pip no avanzaba; la alternativa HTTP oficial se comprobó y conserva un parcial. No se declara CUDA instalada hasta ver `CUDA_VERIFIED` y su evidencia.

El lanzador `start_kev_local.ps1` ahora exige CUDA por defecto, usa BF16 y solo admite CPU con `-CpuOnly`. Se desactiva Xet para el siguiente intento de descarga de pesos, dado el fallo observado de reconstrucción CAS. Esta opción no garantiza que la red complete la descarga.

## Pendientes para cerrar P0

1. Completar instalación CUDA y comprobar que la evidencia identifica RTX 3060 Ti.
2. Completar los pesos Kev fijados y obtener respuesta real desde `/v1/systemone`; no basta un import o tensor CUDA.
3. Medir VRAM/RAM y margen con el generador cargado o con carga alternada. Había unos 5.991 MiB ocupados de 8.192 MiB en la inspección inicial; no se presupone capacidad para ambos modelos simultáneos.
4. Registrar baseline del HEAD final y CI remota antes de integración en main. No se ha publicado ni fusionado esta entrega.

Después: contratos comunes P1, banco de evaluación P2 y adaptaciones medibles del motor. El cliente de decisiones todavía no debe decidir permisos ni activar herramientas por confianza.
