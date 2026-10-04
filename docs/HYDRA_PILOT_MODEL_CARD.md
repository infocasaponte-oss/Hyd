# HYDRA piloto 1.5B — candidato local

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Construido el 29 de septiembre de 2026. Estado: candidato experimental, pendiente de validación ampliada; `approved=false`.

## Pesos y procedencia

- Base: Qwen/Qwen2.5-Coder-1.5B-Instruct, revisión `2e1fd397ee46e1388853d2af2c993145b0f1098a`.
- Corpus: HYDRA sintético verificado, 192 ejemplos de entrenamiento, 32 de validación y 64 de prueba; familias separadas entre particiones.
- Ajuste: LoRA, una época, rango 8, módulos q_proj/v_proj, semilla 42. Receta: `config/recipes/hydra-pilot.json`.
- Artefacto: `models/hydra-pilot/HYDRA.gguf`, arquitectura qwen2, Q4_K_M, 986.048.064 bytes.
- SHA256: `32fac5fc07053408990439db76fae172c0384019773041f1ce4e1194c084dc92`.
- Manifiesto con hashes por etapa: `models/hydra-pilot/build-manifest.json`.
- Licencia de la base conservada en `models/hydra-pilot/BASE-LICENSE.txt`. Las condiciones del código HYDRA no sustituyen las condiciones de los pesos de origen.

## Comprobación real

El modelo está importado en Ollama como `hydra-local`. El evaluador comprobó que el blob servido coincide con el hash del artefacto construido. El candidato pasó 64/64 casos del holdout piloto, ejecutando las respuestas en Docker sin red. El conjunto solo cubre contar elementos y distancia absoluta: no demuestra capacidad general.

La base original 1.5B, convertida y cuantizada con las mismas herramientas a Q4_K_M, también pasó **64/64**. Diferencia de puntuación: **0**; ninguna mejora ni regresión observada en estos casos. No hay evidencia de que el ajuste supere a la base. Los informes completos y sus identidades están en [la comparación](evidence/pilot-comparison.json), [el candidato](evidence/hydra-pilot-holdout.json) y [la base](evidence/base-1.5b-holdout.json).

Una petición real al motor, en modo fast y local, utilizó `hydra-local`, sin caché, y respondió en 962,53 ms. La respuesta de suma de listas pasó tres comprobaciones ejecutadas después en Docker. El motor había emitido `verified=false`; esta ejecución posterior es evidencia separada, no una verificación interna retroactiva. Una sola petición tampoco es un benchmark de latencia o TTFT.

Medición adicional directa de Ollama mediante streaming: cinco peticiones con el mismo prompt. Primera respuesta: TTFT 10.510,6 ms, con 10.325,9 ms de carga reportados por Ollama. En las cuatro repeticiones siguientes: mediana TTFT 18,7 ms y generación 156,4 tokens/s. El prompt repetido puede beneficiarse de caché de contexto; estas cifras no representan diversidad de carga ni latencia del gateway. No se midió pico de VRAM. [Informe diagnóstico](evidence/hydra-streaming.json).

Validación del código: suite completa 389 passed, 5 skipped antes de añadir la utilidad de streaming; después, 11 pruebas focalizadas de medición, comparación e identidad superadas, incluidas dos nuevas que comprueban la finalización del stream. Ruff y comprobación de espacios correctos.

## Reproducción

```powershell
.\scripts\build_hydra_local.ps1
.\scripts\start_hydra.ps1
# En otra terminal:
py -3.12 -m hydra.training.evaluate_corpus --model hydra-local --build-manifest models/hydra-pilot/build-manifest.json --output data/evaluations/hydra-holdout.json
py -3.12 -m hydra.training.compare_evaluations --base data/evaluations/base-1.5b-holdout.json --candidate data/evaluations/hydra-holdout.json --output data/evaluations/pilot-comparison.json
py -3.12 -m hydra.training.measure_inference
```

La comparación requiere un informe completo de la base 1.5B sobre el mismo holdout. Rechaza informes parciales, conjuntos distintos y ausencia de identidad del modelo; recalcula las puntuaciones a partir de los casos. No aprueba despliegues.

## Trabajo pendiente

Ampliar el corpus con tareas verificadas de más familias y procedencia documentada; mantener un nuevo conjunto reservado fuera del ciclo de ajuste. Medir herramientas/JSON, privacidad, robustez, TTFT y memoria. Comparar el checkpoint fusionado con el GGUF para cuantificar pérdidas de cuantización. Validar shadow, canary y rollback antes de activar la promoción automática. No se han publicado estos pesos ni aprobado una release.
