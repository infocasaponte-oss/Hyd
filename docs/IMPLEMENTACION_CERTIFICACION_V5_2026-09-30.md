# HYDRA v5: estado de la implementación y validación

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Se implementaron el corpus contrastivo, entrenamiento incremental, nuevo GGUF, revisión humana en navegador, pruebas prolongadas y barreras de certificación. **No se certificó ni promocionó el modelo**: quedan fallos de instrucciones y la revisión humana todavía no está completada.

## Modelo y entrenamiento

v5 continúa desde los pesos fusionados de v4, identificados por SHA256 en la receta, sin usar sus particiones de evaluación para entrenar. Corpus `data/hydra-instruction-v5`: 612 ejemplos de entrenamiento, 140 de desarrollo, 140 de calibración y 48 de regresión congelada. Se añadieron 200 ejemplos sintéticos de estados booleanos y ordenación numérica: 120 para entrenamiento y 40 para cada partición de desarrollo y calibración. El test original mantiene su hash byte a byte. La auditoría contabilizó 940 prompts distintos en el corpus completo.

Entrenamiento real CUDA en RTX 3060 Ti: 630,22 segundos, dos épocas configuradas, memoria máxima asignada 3.481.800.704 bytes. Modelo textual de 1.543.714.304 parámetros. Artefacto: `models/hydra-instruction-v5/HYDRA.gguf`, Q5_K_M, 1.125.049.920 bytes, SHA256 `d767e0a1c75cbff78a6b95058f9440217ed24d294f57dd8e0eb1a3970d846e23`. Alias Ollama `hydra-instruction-v5:latest`.

## Calidad real y límites

| Prueba | v4 | v5 |
| --- | ---: | ---: |
| Desarrollo ampliado, mismo conjunto de 140 | 100/140, 71,43% | 119/140, 85% |
| Calibración ampliada de 140 | No ejecutada en esta ronda | 127/140, 90,71% |
| Regresión original de instrucciones | 24/48 | 24/48 |
| Código congelado en sandbox | 64/64 | 64/64 |

No comparar directamente el 85% ampliado con el 99% anterior sobre solo 100 tareas: el conjunto incorpora 40 desafíos nuevos. En desarrollo, la ordenación de v5 obtuvo 29/30, incluyendo los 20 casos nuevos correctos. JSON obtuvo 10/30: las nuevas redacciones provocan salidas incompletas como `83300,true`. Esto sigue bloqueando la certificación del modelo sin contrato externo. El test antiguo también sigue devolviendo estados como texto en vez de booleanos en consultas ambiguas.

El motor incorpora generación estructurada cuando una petición pide JSON explícitamente y el perfil soporta esa capacidad. Se extendió el reconocimiento a “Devuélveme un JSON”, “Genera un JSON” y “JSON con…”. No se inventan los campos ni se eliminan explicaciones después de generar. El soporte de formato no demuestra por sí solo que los valores sean correctos.

Para peticiones completas de ordenación ascendente con una lista numérica JSON explícita, el motor puede usar `numeric_sort`. Conserva repeticiones y rechaza booleanos, cadenas, valores no finitos, múltiples listas e instrucciones adicionales. Está habilitado mediante `deterministic_first` en el Studio experimental; el ajuste global por defecto no cambia. Una llamada real devolvió `[-54,3,29,29]` en 0,3 ms, con `models_used=[]`, `tools_used=[solver:numeric_sort]` y `verified=true`. Este resultado no se contabiliza como inferencia del GGUF.

## Estabilidad medida

Prueba de 900,59 segundos, **1.330 inferencias reales del GGUF**, sin respuestas de caché: 1.330 resultados correctos en tres contratos sintéticos repetidos, cero errores, cero cambios de respuesta, mediana 120,18 ms, p95 205,31 ms. Los snapshots de residencia del candidato reportaron 1.244.418.538 bytes de VRAM y crecimiento observado cero. También se hicieron comprobaciones del motor cada 30 segundos, exigiendo el candidato correcto y `use_cache=false`.

Es una prueba acotada de 15 minutos, no una garantía de funcionamiento durante días ni de memoria de todos los procesos. Hubo evaluaciones y pruebas de software concurrentes durante parte de la ejecución. Se preservó la identidad del GGUF antes, durante y después. Evidencia: `docs/evidence/instruction-v5-soak-15m.json`.

## Revisión de tus archivos

Los tres archivos con IDs 1–100, 101–200 y 201–300 se guardaron como test externo `data/external-evaluation-v2`. **300 registros, 287 preguntas únicas**: los 13 registros repetidos permanecen visibles y no suman casos independientes. Ningún prompt normalizado coincide con el entrenamiento de v5. Se conservan hashes de los tres archivos y del conjunto combinado; no se han entrenado ni modificado las referencias.

Se generaron respuestas reales del GGUF para los 300 registros: 136 coincidencias automáticas orientativas. Las demás no se califican automáticamente como fallos: definiciones, sinónimos y huecos abiertos requieren juicio humano. Hay casos ambiguos y referencias potencialmente demasiado restrictivas. Autoría registrada como **aportada por el usuario, sin atestación**, no inventada por el sistema.

Abre http://127.0.0.1:18086/hydra/v1/evaluation/review. Escribe tu nombre, revisa pregunta/referencia/respuesta, marca Correcta/Incorrecta/Ambigua y pulsa Guardar y siguiente. Las ambiguas requieren una explicación; la interfaz permite volver y corregir valoraciones y descargar la revisión. Declara el origen real de las preguntas con el selector; admite humano, mixto, IA o desconocido. Guía: `docs/COMO_REVISAR_HYDRA_2026-09-30.md`.

Cada revisión se vincula al hash del candidato y al test congelado. Las rutas de datos y escritura comparten la autenticación del gateway. Los ambiguos no se eliminan del denominador para inflar la precisión. Las escrituras tienen reemplazo atómico y reintentos acotados ante bloqueos temporales de Windows. Una evaluación se reanuda solo si identidad, dataset, opciones y orden de casos permanecen iguales.

## Estado de certificación

`scripts/check_instruction_certification.py` emite un informe de requisitos, sin modificar manifests ni desplegar modelos. Exige desarrollo, calibración, regresiones, estabilidad, revisión humana completa con suficientes preguntas únicas, autoría declarada y medidas vinculadas al mismo GGUF. La precisión humana conserva todos los casos únicos en el denominador y exige más del 90% con límite inferior Wilson de al menos 0,90.

La promoción permanece bloqueada por desarrollo del 85%, regresión original del 50% y revisión humana pendiente. No se bajaron umbrales, no se sustituyó el test ni se llamaron humanos a datos sintéticos. El siguiente entrenamiento tendrá que reforzar generación de objetos completos y seguir evaluando fuera del entrenamiento; los casos externos revisados no deberán convertirse en ejemplos de entrenamiento del mismo candidato.

## Servicios y pruebas

Studio v5 separado: http://127.0.0.1:18086/studio. Studio 18085 sigue siendo v4 y CeltIA no se modifica. Kev se restaura después del entrenamiento y la prueba de estabilidad; mantiene su política de autoridad restringida y no se atribuye a Kev la mejora de ordenación del GGUF.

La batería general pasó **563 pruebas, 5 omitidas**, en 460,72 segundos. Después de los ajustes de revisión y reconocimiento JSON pasaron **49 pruebas enfocadas**. Ruff y `git diff --check` pasaron. Evidencias de calidad en `instruction-v5-summary.json`, auditoría en `instruction-v5-audit-2026-09-30.json`, decisiones de certificación en `instruction-v5-certification-gates.json`.
