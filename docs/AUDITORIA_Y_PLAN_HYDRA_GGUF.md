# Auditoría y plan de finalización: motor HYDRA + modelo GGUF

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 29 de septiembre de 2026. Inspección iniciada el día 28, hora de Madrid.

## Dictamen

Existe una implementación amplia del motor HYDRA y de su fábrica de modelos. Todavía no hay evidencia suficiente para declarar terminado el producto motor + modelo: no se encontraron pesos `.gguf`, `.safetensors` ni datasets `.jsonl` dentro de `D:\HYDRA`; la evaluación del entrenamiento contiene defectos; y las ramas del repositorio representan dos arquitecturas diferentes.

El objetivo obligatorio de este plan es entregar **un motor HYDRA instalable y probado que ejecute un modelo HYDRA derivado, entrenado, convertido y evaluado en GGUF**. El GGUF contiene los pesos del modelo; el kernel, herramientas, memoria y políticas siguen siendo software del motor. Convertir o renombrar un modelo base es un hito técnico, pero no demuestra especialización mediante entrenamiento.

La auditoría comprende código, configuración, historial remoto, CI pública, hardware y pruebas automatizadas. No certifica cada módulo, seguridad completa, operación multinodo ni calidad real de inferencia. No se entrenó ni descargó un modelo durante esta auditoría.

## Estado local y GitHub

Repositorio: https://github.com/infocasaponte-oss/HYDRA-SO

| Línea | Commit auditado | Situación |
|---|---|---|
| Local y `origin/hydra-1.0` | `83db303d642ba59acde6f2bfacd9a39033b75024` | Motor `hydra-engine` 1.0.0; árbol inicialmente limpio; 1 commit en esta historia |
| `origin/integration/hydra-1.0` | `5e3ddf563a6bc0ce67fa556e7ebf1f9028038b1e` | Misma arquitectura más CI, autenticación remota y rate limit; 9 commits |
| `origin/main` — predeterminada | `48d0f3a5c9273790a02ff4095623754c3f7cfb6b` | `hydra-so` 0.4.0.dev0; arquitectura alternativa; 392 commits |

`git merge-base HEAD origin/main` no encontró ancestro común. La comparación de árboles presenta 453 archivos cambiados, 11.479 inserciones y 30.978 eliminaciones en dirección local → main: son diferencias entre arquitecturas, no una propuesta de borrado. Integración cambia solo 5 archivos respecto al local, con 140 inserciones y 4 eliminaciones.

La API pública de GitHub devolvió cero issues abiertos, ningún PR en la consulta y ninguna release publicada. La última CI de integración terminó en success: https://github.com/infocasaponte-oss/HYDRA-SO/actions/runs/36489409909. Ejecuta importación, compilación y pytest en Ubuntu/Python 3.12; no demuestra entrenamiento ni cuantización en GPU. La página HTML consultada mostró un estado vacío incoherente; para el inventario se usaron Git remoto y la API REST. `gh` no estaba autenticado, pero esto no impidió inspeccionar el repositorio público.

**Base recomendada:** continuar desde el commit auditado de `integration/hydra-1.0` en una rama `codex/finish-hydra-gguf`. Preservar main e incorporar sus mejoras por comportamiento y pruebas, adaptando interfaces. No mezclar automáticamente árboles sin historia común. Crear una matriz de equivalencias para outbox, supervisor, health/readiness, recuperación y verificación de código; decidir el cambio de rama predeterminada al integrar la versión validada.

## Comprobaciones ejecutadas

| Comprobación | Resultado |
|---|---|
| Local: `py -3.12 -m pytest -q` | **136 passed, 2 skipped**, 34,71 s |
| Snapshot separado de main: mismo comando con `--tb=short` | **174 passed, 4 failed**, 7,34 s |
| Repetición aislada de `test_terminal_commit_is_atomic_with_outbox` en main | Falla de nuevo por orden de tópicos |
| Reproducción de `EvalArena.summarize(EvalReport(...))` | `AttributeError: 'str' object has no attribute 'suite'` |
| Archivos de pesos/dataset en carpeta local | No encontrados por extensiones GGUF/safetensors/JSONL |

Python utilizado: 3.12.10, pytest 9.1.1, pydantic 2.13.5. El alias `python` de Windows falla; `py -3.12` sí funciona. El primer intento sobre main se ejecutó desde el directorio local y mezcló imports: se descartó y se repitió desde `D:\HYDRA-audit-main`. Los números de la tabla corresponden a esa ejecución corregida. Main declara pytest <9; por tanto, su resultado con pytest 9.1.1 es diagnóstico y debe repetirse en su entorno de dependencias declarado.

Se creó también `D:\HYDRA-audit-env` y se verificó la instalación editable de HYDRA con sus dependencias `[dev]` en ese entorno separado. Las suites citadas se ejecutaron con el Python existente mediante `py -3.12`, no en ese nuevo entorno. La copia de main y el entorno quedan fuera del repositorio. La única modificación del árbol de trabajo es este informe; no se modificó código ni se publicaron cambios en GitHub.

Los otros tres fallos de main son un error WinError 10106 al ejecutar una herramienta y dos WinError 1314 al crear symlinks sin privilegio. No se interpretan como fallos demostrados de la lógica de aislamiento. Los dos skips locales corresponden a integración opcional; las pruebas offline no acreditan PostgreSQL/Redis/NATS operativos.

## Hallazgos priorizados

| ID | Prioridad | Evidencia y efecto | Acción de cierre |
|---|---|---|---|
| A01 | P0 | Historias y APIs divergentes; main y local no son versiones intercambiables | Base única, matriz de portado y pruebas de contrato |
| A02 | P0 | `hydra/training/lab.py:523` usa `get('passed', True)` si no existe evaluación | Rechazar/no marcar READY cuando falte evidencia; test sin evaluador y sin métricas |
| A03 | P0 | `hydra/training/lab.py:422` itera claves de un dict como objetos; también espera `s.cases` y `report.model`, incompatibles con `EvalReport` | Unificar contrato con `hydra/evals/engine.py`; prueba de arena usando informes reales |
| A04 | P0 | No hay artefacto HYDRA GGUF ni entrenamiento verificable dentro del proyecto | Ejecutar pipeline completo y conservar pesos, hashes, dataset y evaluaciones |
| A05 | P1 | `hydra/api/main.py` local acepta peticiones sin clave configurada; integración ya restringe acceso remoto | Incorporar corrección y probar rutas HTTP/WebSocket administrativas relevantes |
| A06 | P1 | `hydra/model_factory/validator.py` permite tool score 0 y omite restricciones de memoria/latencia cuando falta medida | Perfiles de aceptación explícitos; evidencia ausente bloquea promoción |
| A07 | P1 | `tests/test_factory.py:87` sustituye proveedor Ollama por mock | Añadir test real de convertir → cargar GGUF → inferir → evaluar → registrar |
| A08 | P1 | `scripts/bootstrap_windows.ps1` clona llama.cpp sin fijar commit; dependencias sin lock | Fijar versiones y CUDA/toolchain; verificar argv con binarios de esa revisión |
| A09 | P1 | main ordena outbox por `created_at, id`; el test de secuencia falla | Investigar empates de timestamp y definir secuencia monotónica si el contrato exige orden |
| A10 | P1 | README anuncia estación validada, pero esta auditoría no halló informes de GPU/versiones/mediciones en el árbol | Adjuntar informes reproducibles y limitar afirmaciones a evidencia |
| A11 | P1 | `Training Lab` y `model_factory/train_lora.py` mantienen caminos distintos; el script TRL no configura 4 bits explícitamente para qlora | Unificar receta y backend; verificar método efectivo, tokenizer y merge |

READY no equivale por sí solo a despliegue en producción; A02 señala una clasificación de candidato sin evaluación, no una promoción automática demostrada.

## Hardware y preparación

Se detectó RTX 3060 Ti de 8.192 MiB, aproximadamente 32 GiB de RAM y 779 GB libres en D:. Durante la captura había 6.187 MiB de VRAM ocupados. No asumir que los 8 GB estarán disponibles durante entrenamiento. La versión CUDA indicada por nvidia-smi no prueba que el toolkit de compilación esté instalado.

Ollama está instalado y enumera, entre otros, qwen3:8b, qwen2.5-coder:7b/14b, llama3.2:1b y celtia-qwen3. Esto acredita modelos locales en Ollama, no un artefacto HYDRA entrenado y exportado. `llama-server` y `llama-quantize` no aparecen en PATH; no se afirma que estén ausentes de todo el disco.

Para la primera especialización se propone conservar el candidato ya definido en `config/recipes/coder-lora.yaml`: Qwen2.5-Coder-1.5B-Instruct. Es una elección inicial de alcance, pendiente de baseline, compatibilidad, términos de uso y prueba de memoria. No prometer entrenamiento de 7B/8B en esta GPU sin medirlo. Fuente del candidato: https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct.

## Plan de ejecución con puertas de aceptación

Las estimaciones son días de trabajo de ingeniería para una persona; excluyen esperas de descarga, duración completa de entrenamiento y revisión del corpus. No representan una fecha comprometida.

| Fase | Trabajo y entregable | Dependencia | Criterio para avanzar | Estimación |
|---|---|---|---|---|
| F0 — Consolidación | Rama desde integración, matriz de módulos, entorno reproducible y lock de dependencias | Ninguna | Instalación limpia; tests de integración y baseline local registrados; árbol reconciliado sin pérdida de capacidades | 1–2 días |
| F1 — Motor HYDRA | Resolver A02/A03/A05/A06; presupuestos, timeout/cancelación, sandbox, persistencia, supervisión y rollback; portar mejoras pertinentes de main | F0 | CLI/API completan tareas con modelo local real; fallos de backend no producen éxito ficticio; tests Windows/Linux | 3–5 días |
| F2 — GGUF de referencia | Instalar llama.cpp fijado, descargar fuente con revisión y hashes; convertir F16/BF16; cuantizar Q4_K_M; cargar e inferir | F0; puede avanzar junto a F1 | GGUF real, hash, log de construcción y smoke test; baseline de calidad/recursos | 1–3 días |
| F3 — Corpus HYDRA | Recopilar tareas verificadas de código, herramientas y español; derechos/procedencia, redacción, dedup; train/validation/test separados por proyecto/fuente | F1 | Dataset versionado, manifiesto, sin solapamiento conocido y holdout congelado antes de entrenar | 3–7 días |
| F4 — Especialización | Piloto LoRA/QLoRA de memoria; entrenamiento, validación, semillas y checkpoints; merge con base exacta | F2 + F3 | Adaptador no vacío, pérdidas registradas, inferencia del checkpoint y mejora medible frente a base | 2–4 días + cómputo |
| F5 — HYDRA GGUF | Merge → safetensors → GGUF F16/BF16 → Q4_K_M; imatrix con datos separados del test; variante Q5 solo si aporta valor medido | F4 | `HYDRA-Coder-1.5B-v1-Q4_K_M.gguf` carga; tokenizer/template correctos; hashes y linaje completos | 1–3 días |
| F6 — Validación conjunta | Base vs ajustado vs GGUF; pruebas por categorías, fallos, privacidad, tools/JSON; medir VRAM/RAM, tokens/s, TTFT p50/p95 | F1 + F5 | Gates abajo cumplidos y motor selecciona el hash exacto del GGUF; ninguna sustitución mock en evidencia real | 2–4 días |
| F7 — Entrega | Wheel motor, modelo, model card, informes, instalador/configuración, checksum, firma, release y rollback | F6 | Instalación desde cero reproduce arranque y pruebas de aceptación; usuario puede ejecutar motor + modelo offline | 1–2 días |

Total orientativo: 14–30 días de ingeniería, revisable tras F2 y F3. La amplitud restante de clúster, federación y multimodalidad requiere planificación adicional; no debe bloquear el primer producto local si queda declarada como experimental.

## Gates propuestos para el producto local

Estos son objetivos de aceptación por fijar antes del entrenamiento, no resultados obtenidos:

- Todos los tests obligatorios del motor pasan en Windows y Linux; integración externa tiene entorno explícito y no se contabiliza un skip como aprobación.
- Suite real mínima de 100 tareas con informes individuales; ampliar y separar los casos repetidos del actual E2E-100 para reducir sesgo. Holdout independiente del corpus y la calibración.
- Especialista mejora la categoría objetivo frente al modelo base; ninguna categoría esencial pierde más de 3 puntos porcentuales. Reportar tamaño de muestra e incertidumbre.
- GGUF pierde como máximo 3 puntos frente al checkpoint ajustado en calidad global; JSON válido >=95% y herramientas correctas >=90% en tareas dentro de su alcance.
- Cero violaciones de privacidad/política en la batería definida; esto no equivale a garantía universal.
- Cero OOM en la batería y prueba sostenida; contexto inicial 2K, ampliar a 4K/8K solo con medición. Registrar recursos libres y pico. Definir presupuesto de latencia en F2 y bloquear release si falta la medida.
- Artefacto obligatorio: archivo GGUF autónomo de pesos completos. Un alias Ollama o un adaptador LoRA GGUF no satisface por sí solo la entrega.
- Reproducción trazable con commit HYDRA, revisión base, versión llama.cpp, versiones de entrenamiento, receta, dataset, semillas, hashes y limitaciones de determinismo.

## Paquete final obligatorio

1. Motor HYDRA versionado, instalable, CLI/API, configuración del modelo y manual de operación.
2. `HYDRA-Coder-1.5B-v1-Q4_K_M.gguf` como nombre propuesto; modelo derivado identificado como tal.
3. Adaptador/checkpoint y manifiesto del merge conservados para reconstrucción.
4. `SHA256SUMS`, manifiesto firmado y model card con base, procedencia, restricciones y evaluación.
5. Informes baseline/ajustado/GGUF y motor completo, con recursos y comandos reproducibles.
6. Publicación de pesos en almacenamiento de artefactos apropiado y referencias en Git; no introducir pesos grandes en el historial ordinario.

El proyecto local se declara terminado únicamente cuando **motor + GGUF + evidencia + instalación reproducible** cumplen F7. La presencia de código de entrenamiento o 136 pruebas offline aprobadas no sustituye ese criterio.

## Primer lote implementable

- Crear rama de trabajo desde integración y fijar contratos/entorno.
- Corregir EvalArena con un informe real y bloquear READY sin evaluación.
- Cerrar los gates de evidencia faltante y revisar el backend efectivo de entrenamiento.
- Construir el GGUF baseline y medir la RTX 3060 Ti antes de elegir batch/contexto del entrenamiento.
- Abrir los hitos F0–F7 en GitHub al comenzar implementación, conservando estos criterios de cierre.

Referencia del toolchain: https://github.com/ggml-org/llama.cpp. Sus herramientas soportan inferencia local, conversión y cuantización; los comandos exactos deberán validarse contra la revisión fijada.
