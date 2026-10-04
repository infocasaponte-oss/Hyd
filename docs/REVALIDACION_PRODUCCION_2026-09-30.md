# Revalidación de HYDRA v5 para producción

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 2026-09-30. Candidato: HYDRA 1.5B v5, GGUF Q5_K_M.

## Decisión

No promocionar. Se repitió la inferencia con resultados nuevos, separados de los informes anteriores. El desarrollo sigue por debajo del objetivo y no existen revisiones humanas guardadas. No se modificaron los pesos para adaptar el modelo a las respuestas del test congelado.

## Resultados nuevos

| Comprobación | Resultado |
|---|---:|
| Desarrollo, generación directa | 119/140, 85% |
| Conjunto separado de calibración, generación directa | 127/140, 90,71% |
| Instrucciones congeladas, generación directa | 24/48, 50% |
| Mismas instrucciones con contrato JSON tipado | 48/48, 100% |
| Regresión de programación | 64/64 |
| Evaluación externa | 300 respuestas; 136 coincidencias automáticas |
| Valoraciones humanas guardadas | 0/287 casos únicos |
| Pruebas del repositorio | 569 aprobadas, 5 omitidas |
| Pruebas focalizadas tras las correcciones | 39 aprobadas |
| Estabilidad real en GPU, 15 minutos | 1.411 inferencias; cero fallos y cero cambios de salida |

Durante la estabilidad, la memoria GPU del modelo se mantuvo en 1.244.418.538 bytes, sin crecimiento; latencia mediana 124,90 ms y percentil 95 de 222,22 ms. Las comprobaciones adicionales del motor también pasaron. Este ensayo acotado no equivale a certificar todos los usos ni a una prueba de carga concurrente.

Las coincidencias automáticas de las respuestas externas no son una medida de precisión humana: las explicaciones y las referencias ambiguas necesitan valoración semántica. Los 300 registros contienen 287 preguntas únicas. No se usan para entrenar.

El 48/48 pertenece al protocolo configurado, que exige tipos JSON en un contrato acotado; no demuestra una mejora de los pesos. El resultado directo 24/48 se mantiene para permitir comparaciones honestas. La exactitud medida sobre el conjunto de calibración no demuestra por sí sola que las probabilidades del modelo estén calibradas.

## Integridad y correcciones

SHA-256 del GGUF: `d767e0a1c75cbff78a6b95058f9440217ed24d294f57dd8e0eb1a3970d846e23`.

Se comprobaron los artefactos de entrenamiento, fusión, conversión y cuantización; 940 solicitudes distintas entre las particiones. Entrenamiento CUDA. Modelo de texto, sin visión.

Se corrigió el guardado del evaluador externo para tolerar bloqueos transitorios de archivos en Windows. El primer intento quedó incompleto y se conservó hasta completar un segundo intento íntegro. La comprobación de promoción ahora acepta una carpeta de evidencias nueva, exige completar el proceso y las pruebas, y recalcula las revisiones humanas desde sus registros en vez de confiar en contadores.

Evidencias de esta ejecución: `docs/evidence/revalidation-v5-2026-09-30-r1/`. Estabilidad: `docs/evidence/revalidation-v5-2026-09-30-r1-soak.json`. El informe `instruction-v5-certification-gates.json` identifica los requisitos pendientes.

## Trabajo necesario para aprobar

1. Corregir la generalización de las peticiones de objetos JSON mediante ejemplos nuevos de desarrollo y entrenamiento; mantener fuera las respuestas de evaluación.
2. Repetir entrenamiento, evaluación separada y cuantización si cambian los pesos. Si se certifica solo el motor con contratos, declarar ese alcance y evaluar su configuración completa, sin presentar sus resultados como precisión del GGUF directo.
3. Completar la revisión externa y declarar honestamente la procedencia humana o sintética. Para una afirmación de precisión humana independiente, el test debe tener autoría e independencia acreditadas.
4. Superar los criterios de calidad y estabilidad antes de modificar producción. Las pruebas de software o un contrato JSON correcto no sustituyen la evaluación de calidad.

Revisión: http://127.0.0.1:18086/hydra/v1/evaluation/review

Studio experimental: http://127.0.0.1:18086/studio
