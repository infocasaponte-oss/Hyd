# Informe de HYDRA v8 — 1 de octubre de 2026

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Estado

El fine-tuning terminó en la RTX 3060 Ti. El adaptador se fusionó y se generó un **HYDRA.gguf Q5_K_M de 1.125.049.920 bytes**. Está importado en Ollama como `hydra-instruction-v8:latest` y probado mediante inferencia real en GPU.

**No cumple los criterios para producción.** El motor configurado pasa el contrato JSON conocido, pero el modelo sigue mostrando debilidades de generación libre y generalización.

## Resultados separados por protocolo

| Prueba | v7 | v8 | Interpretación |
| --- | ---: | ---: | --- |
| Desarrollo nuevo, subconjunto automático | 16/31 | 17/31 | 51,61% → 54,84%; dos mejoras y una regresión, diferencia no significativa (McNemar p=1). |
| Calibración reservada, subconjunto automático | No repetida | 6/26 | 23,08%; insuficiente. Es evaluación de un conjunto reservado, no calibración de confianza predictiva. |
| Instrucciones congeladas, generación libre | 24/48 | 24/48 | Los 24 literales pasan; los 24 JSON fallan. Es una ejecución nueva vinculada al hash de v8. |
| Mismo test, contrato JSON tipado | 48/48 previamente | 48/48 | Las restricciones de salida ayudan; no prueban mejora de los pesos en generación libre. |
| Motor configurado, JSON conocido, sin caché | 78/78 previamente | 78/78 | Todas las llamadas de v8 usaron el candidato correcto. No equivale a precisión general del chat. |

Nueve casos del desarrollo y nueve de calibración requieren revisión semántica humana. El evaluador no cuenta palabras clave como prueba de corrección.

La referencia inicial v7 de 15/31 se conserva. Las mismas respuestas se recalcularon como 16/31 al aceptar la equivalencia completa «Pack B»/«el pack B», sin aceptar subcadenas ni respuestas contradictorias. V8 se puntuó con ese mismo criterio.

Se generaron también las 300 respuestas del test externo para v8, con 141 coincidencias automáticas de referencia. Ese número **no es una precisión humana**: preguntas abiertas y respuestas equivalentes necesitan revisión. Hay 287 casos únicos; las valoraciones anteriores pertenecen a v7 y no se transfieren a v8.

## Qué se corrigió

- Importación conservando los originales, la procedencia y hashes de los 11 archivos suministrados.
- Separación de desarrollo y calibración: 133 nuevos ejemplos entrenables, 40 de desarrollo y 35 de calibración. Totales con replay: **969/228/223/48**. El test congelado no cambió.
- Ocho ejemplos JSON de desarrollo añadidos; el paquete original no tenía ninguno en validación.
- Entrenamiento con pérdida solo sobre la respuesta, prefijo de tokens comprobado y rechazo de respuestas truncadas.
- Selección del mejor checkpoint por pérdida de desarrollo; fusión y exportación mediante la fábrica de Windows, con directorios y artefactos separados.
- Comparador con hashes, misma cuantización y parámetros, preservación de tipos JSON y coincidencia completa para resultados numéricos. Los contenidos abiertos quedan pendientes de revisión.
- Contador de revisión completo basado en casos únicos, sin exigir valorar duplicados.
- Registro y recuperación de checkpoint tras reinicio del equipo.

Pasaron **44 pruebas de software enfocadas** y Ruff. No se presenta como una ejecución nueva de toda la suite del repositorio.

## Entrenamiento y recuperación

La base fue el HF fusionado de v7, fijado por SHA256. LoRA de rango 16 sobre proyecciones de atención, dos épocas, tasa 2e-5 y batch 1 con acumulación 8.

El equipo se reinició a las 01:42:52. La ejecución interrumpida llegó al paso 197/242, pero solo podía recuperarse desde el checkpoint completo 121. Se archivó intacta y se reanudó desde una copia con hashes verificados. El checkpoint final 242 fue seleccionado por pérdida de desarrollo.

Todos los parámetros entrenados estaban en `cuda:0`. El pico medido fue 6.054.632.960 bytes de VRAM. Después de terminar se ajustó el tamaño de batch de evaluación por defecto para futuras ejecuciones, reduciendo la presión de memoria. Esa modificación no se atribuye al entrenamiento ya concluido: se conservó su código exacto en `models/hydra-instruction-v8/source-train_lora.py`.

## Cómo probarlo

- Studio experimental v8: **http://127.0.0.1:18088/studio**.
- Revisión de respuestas v8: **http://127.0.0.1:18088/hydra/v1/evaluation/review**.
- Studio v7 restaurado: http://127.0.0.1:18087/studio.

Los tres servicios comprobados responden HTTP 200: Studios v7/v8 y `/v1/models` de Kev en el puerto 8009. Kev vuelve a CUDA/bfloat16 y sigue en sombra; no se le concede nueva autoridad. CeltIA no se modificó.

En Studio v8, probar una petición de JSON y después una de razonamiento. El éxito de la primera no garantiza el de la segunda. Para una comparación reproducible usar los scripts y evidencias, no conversaciones con historiales diferentes.

## Qué falta y siguiente ensayo

No se promociona v8: desarrollo y calibración generales son bajos, JSON libre sigue fallando y falta nueva revisión humana vinculada a estos pesos y estabilidad prolongada.

El siguiente ensayo debe probar replay equilibrado (este candidato conserva 836 ejemplos antiguos frente a 133 nuevos), más ejemplos verificados por habilidad y variantes de JSON, y adaptadores que incluyan las capas MLP. Seleccionar recetas solo por desarrollo; reservar calibración y mantener los tests como regresión. El paquete actual no contiene una cobertura completa de todos los conceptos que fallaron, como MoE/GQA, y no debe prometerse que los enseña.

La prueba de 15 minutos y una evaluación humana independiente siguen pendientes. No se ejecutó una promoción ni se cambió el modelo de producción.

## Evidencias

- GGUF: `models/hydra-instruction-v8/HYDRA.gguf`.
- SHA256: `0ef14148ababf98c52623f164d776ed76f17a583175ea91301e024a157231761`.
- Construcción y métricas: `models/hydra-instruction-v8/build-manifest.json`, `adapter/metrics.json`.
- Comparación: `docs/evidence/instruction-v8-supplied-comparison.json`.
- Calibración: `docs/evidence/instruction-v8-supplied-calibration.json`.
- Test libre/tipado: `docs/evidence/instruction-v8-frozen-raw.json`, `instruction-v8-frozen-typed.json`.
- Motor: `docs/evidence/instruction-v8-json-engine-live.json`.
- Respuestas externas: `docs/evidence/external-evaluation-v8.json`.
- Estado de aceptación: `docs/evidence/instruction-v8-acceptance.json`.

La guía `docs/FINE_TUNING_V8_Y_REVISION_CONJUNTA.md` permite compartir receta, cambios y evidencias con Claude. No hubo coordinación directa con Claude en esta ejecución ni se atribuye su aprobación.
