# Ajuste v8: paquete corregido y revisión conjunta

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Los archivos suministrados se conservan en `workspace/finetuning-v8/originals`. La implementación corregida se integra en HYDRA para reutilizar la fábrica existente y evitar dos pipelines divergentes. Los archivos de Downloads no se modifican.

| Propuesta original | Implementación corregida |
| --- | --- |
| generar_dataset.py y corpus | scripts/prepare_supplied_finetuning.py; hydra/training/finetuning_v8.py |
| conceptos_tecnicos.py | Referencias importadas con procedencia; corregida la equivalencia errónea entre inmutabilidad y posibilidad de usar cualquier objeto como clave |
| comprobar_contaminacion.py | scripts/check_supplied_contamination.py, compatible con JSON, JSONL, prompt, question y messages; no elimina filas |
| entrenar_lora.py | hydra/model_factory/train_lora.py con prefijo de tokens exacto, rechazo de respuestas truncadas, GPU obligatoria y selección del mejor checkpoint por pérdida de desarrollo |
| fusionar_adaptador.py y exportar_gguf.sh | hydra/model_factory/build_hydra.py; ejecución desde Python en Windows, directorio independiente, conversión y cuantización Q5_K_M, manifiesto y hashes |
| evaluar_comparar.py | scripts/compare_supplied_finetuning.py: inferencia Ollama real, hashes, misma configuración, tipos JSON, coincidencia completa y revisión humana para semántica |

## Receta

`config/recipes/hydra-instruction-v8.json` fija los pesos HF fusionados de v7. Dos épocas LoRA, tasa 2e-5, rango 16, acumulación 8, batch 1, GPU obligatoria. No modifica las rutas de producción ni CeltIA.

El corpus se prepara una vez en una carpeta nueva. Nuevos ejemplos: 133 de entrenamiento, 40 de desarrollo (32 suministrados y ocho JSON generados), 35 de calibración reservados de los 168 originales. Se conservan íntegros los splits del padre: totales 969/228/223/48. La calibración no interviene en la selección del checkpoint. La pérdida de desarrollo no se presenta como confianza calibrada.

```powershell
# Ya preparado: no repetir sobre la misma carpeta.
.venv\Scripts\python -m scripts.prepare_supplied_finetuning

.venv\Scripts\python -m hydra.model_factory.build_hydra --recipe config/recipes/hydra-instruction-v8.json --check
.venv\Scripts\python -m hydra.model_factory.build_hydra --recipe config/recipes/hydra-instruction-v8.json
.venv\Scripts\python -m scripts.register_instruction_candidate --version 8

.venv\Scripts\python -m scripts.compare_supplied_finetuning --version 8 --output docs/evidence/instruction-v8-supplied-dev-candidate.json
.venv\Scripts\python -m scripts.compare_supplied_finetuning --compare docs/evidence/instruction-v8-supplied-dev-baseline-v7-r2.json docs/evidence/instruction-v8-supplied-dev-candidate.json --output docs/evidence/instruction-v8-supplied-comparison.json
```

Usar nombres nuevos para nuevas ejecuciones. Los resultados no se sobrescriben. No ejecutar todo.jsonl como entrenamiento: contiene desarrollo y calibración.

## Revisión entre Codex y Claude

No hay comunicación directa con Claude en esta sesión. Se puede compartir este documento, la receta, el diff y las evidencias con Claude, y traer sus observaciones al proyecto. La revisión debe señalar archivos y líneas, explicar el fallo y proponer una prueba que lo detecte. Codex puede contrastarla con los resultados y aplicar correcciones reproducibles.

El acuerdo entre dos asistentes no sustituye la validación humana ni habilita por sí solo producción. Revisar especialmente separación de datos, calidad de referencias, regresiones, offload CUDA y correspondencia entre los pesos probados y el GGUF distribuido.

Las 287 valoraciones humanas anteriores pertenecen a v7: no se heredan como aciertos de v8. Los tests conocidos siguen siendo regresión. Una nueva prueba humana independiente y la estabilidad prolongada siguen siendo requisitos para certificación general.

## Recuperación del reinicio del equipo

El equipo se reinició el 1 de octubre a las 01:42:52. La primera ejecución llegó al paso 197/242, pero su último checkpoint completo era el paso 121. Se conservó en `models/hydra-instruction-v8-interrupted-r1` con estado `INTERRUPTED_HOST_REBOOT`.

La receta nueva fija los hashes del checkpoint de recuperación. Se copió a `runtime/instruction-v8-resume-checkpoint-121` para ajustar únicamente la ruta del mejor checkpoint en trainer_state.json; pesos, optimizador, scheduler y RNG no cambiaron. El proceso reanudado se lanzó separado de la terminal para resistir una interrupción del chat. Un reinicio del equipo seguirá requiriendo recuperación explícita.

La referencia inicial 15/31 se conserva. Al corregir la equivalencia completa «Pack B»/«el pack B», las mismas respuestas dan 16/31 en el informe r2. No se repitió ni alteró la generación para recalcular esa referencia.

Fuente primaria de la corrección sobre hashability e inmutabilidad: [glosario de Python](https://docs.python.org/3/glossary.html#term-hashable).
