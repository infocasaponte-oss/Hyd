# Motor HYDRA y construcción local de HYDRA.gguf

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Estado de implementación: 29/09/2026, en `main` desde HYDRA 1.1 (PR #13). Se desarrolló en la rama `codex/finish-hydra-gguf`.

**Actualización:** el candidato 1.5B ya se construyó y completó la evaluación piloto. Consultar [la ficha actual del modelo](HYDRA_PILOT_MODEL_CARD.md). Las incidencias de descarga descritas más abajo son el historial inicial, ya resuelto; no representan el estado actual.

## Entregas verificadas

- Motor empaquetado en `dist/hydra_engine-1.0.0-py3-none-any.whl`, incluyendo configuración. Se instaló en un entorno separado y respondió correctamente a una tarea offline fuera del árbol fuente.
- Autenticación remota y rate limit de integración incorporados al partir de esa rama.
- EvalArena compatible con EvalReport; informes vacíos/incomparables no aprueban candidatos.
- Training Lab rechaza evaluación ausente, falsa o que no devuelva el booleano `true`.
- QualityGate bloquea suites ausentes y falta de mediciones cuando se configuran límites.
- Recetas del Training Lab y trabajos PEFT unificados; entrenamiento con pérdida solo sobre la respuesta, checkpointing, semilla, métricas de validación y comprobación BF16.
- QLoRA deja de pasar silenciosamente por el script TRL sin configuración de 4 bits; requiere el backend PEFT y bitsandbytes.
- Pipeline reanudable: validación de entradas → LoRA → merge → GGUF F16 → Q4_K_M → manifiesto y SHA256SUMS. No promociona automáticamente.
- Exportación de GGUF desde Ollama, con comprobación de hash, licencia y estado explícito de baseline.

## Evidencia de ejecución

La suite completa terminó con **149 passed, 2 skipped**. Los skips son integración opcional con infraestructura externa. También se verificaron sintaxis Python/PowerShell y la instalación del wheel fuera del checkout.

El motor respondió con `qwen2.5-coder-7b` real a una pregunta sobre funciones puras. No se usó el proveedor mock; esas respuestas informativas quedaron con `verified=False`, por lo que no se presentan como prueba de verificación semántica. Dos ejecuciones tardaron aproximadamente 270 y 90 segundos con configuración multimodelo; queda pendiente optimizar y medir latencias de la configuración del candidato.

`models/HYDRA-baseline.gguf` es una copia comprobada de los pesos locales `qwen2.5-coder:7b`, Q4_K_M, 4.683.074.048 bytes. SHA256:

```text
60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463
```

Se importó ese archivo en Ollama como `hydra-baseline` y superó **64/64 casos** del holdout piloto, ejecutando sus respuestas en Docker. Informe: [baseline-holdout.json](evidence/baseline-holdout.json). Este resultado solo cubre dos familias sintéticas sencillas: contar elementos y distancia absoluta. No demuestra calidad general ni mejora por entrenamiento. El manifiesto mantiene `approved=false`.

El entrenamiento PEFT se ejecutó con éxito en un modelo Qwen2 diminuto de pesos aleatorios creado exclusivamente para comprobar el pipeline. Se comprobaron guardado del adaptador, métricas, merge, conversión y cuantización. Los artefactos de esa prueba permanecen en `data/training-smoke`; **no son un modelo HYDRA utilizable**. El cuantizador recurrió a precisiones alternativas en tensores pequeños de esa prueba.

## Corpus propio

```powershell
py -3.12 -m hydra.training.verified_corpus
```

Genera 192 ejemplos de entrenamiento, 32 de validación y 64 de prueba en `data/hydra-corpus-v1`, con hashes y separación por familias. Las respuestas de las plantillas se verifican contra casos deterministas. El generador no ejecuta código proporcionado por modelos. El evaluador de respuestas generadas usa Docker sin red.

Es un corpus piloto reproducible y limitado, creado para comprobar la especialización y la fábrica. El corpus de producto debe crecer con tareas variadas verificadas, procedencia y evaluación independiente. No se promete que este piloto mejore la base.

## Bloqueo actual del modelo especializado

Falta completar `models/base/model.safetensors` del candidato Qwen2.5-Coder-1.5B-Instruct, revisión `2e1fd397ee46e1388853d2af2c993145b0f1098a`. Tamaño esperado: **3.087.467.144 bytes**. La descarga inicial acabó con curl error 18 (respuesta incompleta); un intento reanudado limitado a 90 segundos terminó con error 28. Quedaron 22.544.410 bytes en `model.safetensors.partial`.

El preflight rechaza esa entrada incompleta. **No existe todavía el `models/hydra-pilot/HYDRA.gguf` especializado ni se ha entrenado el candidato 1.5B.** El baseline exportado conserva su nombre y procedencia propios.

## Exportar la base desde Ollama

Para comparar el candidato con su modelo base sin volver a descargarlo, se pueden exportar los pesos GGUF que Ollama ya tiene en local:

```powershell
python -m hydra.model_factory.export_ollama --model qwen2.5-coder:7b --output models/HYDRA-baseline.gguf
```

El script funciona así:

1. Pide a Ollama (`/api/show`) la ruta real de los pesos.
2. Valida que el fichero sea un GGUF con tensores.
3. Lo copia sin sobrescribir nada y comprueba el SHA-256 de la copia.
4. Junto al `.gguf` escribe:
   - `.manifest.json`, con el modelo de origen, la ruta, el hash, la arquitectura y la cuantización, y con `status: BASELINE_NOT_HYDRA_TRAINED` y `approved: false`: es una línea base, no un modelo entrenado por HYDRA;
   - `.LICENSE.txt`, con la licencia que declara Ollama.

## Reanudar y construir

Actualización de implementación: existe un comando único que prepara los pesos, conserva el corpus existente, comprueba entradas y ejecuta entrenamiento, fusión y GGUF:

```powershell
.\scripts\build_hydra_local.ps1
```

El progreso queda en `runtime/build-local-status.json`, la transcripción en `runtime/build-local.log` y los logs de cada etapa en `models/hydra-pilot`. Un bloqueo de archivo impide dos ejecuciones simultáneas de este comando. Si falla, el estado pasa a `FAILED`; no promociona ni sirve el candidato automáticamente. La descarga admite hasta cuatro horas por intento y conserva el parcial. Solo lo renombra tras comprobar el tamaño y SHA256 fijados. El tiempo real depende de red y hardware.

Desde `D:\HYDRA`:

```powershell
.\scripts\prepare_hydra.ps1
.\.venv\Scripts\python.exe -m hydra.model_factory.build_hydra --check
.\.venv\Scripts\python.exe -m hydra.model_factory.build_hydra
```

La preparación reanuda descargas y verifica el SHA256 fijado de los pesos. Se fijó llama.cpp `b11146` y se comprobó el arranque de `llama-quantize.exe` y del conversor. El entorno `.venv` reutiliza torch 2.5.1+cu121 instalado; CUDA está disponible. Las versiones principales adicionales están en `scripts/requirements-training.txt`; ese archivo no es un lock completo de dependencias transitivas.

El pipeline utiliza una época LoRA, rango 8, batch 1, acumulación 8 y longitud 256 para el piloto. La viabilidad de memoria del modelo 1.5B completo debe comprobarse al completar la descarga; el éxito del modelo diminuto no la garantiza.

Si una etapa falla, se guarda el error y el log. Al repetir, se reutilizan etapas completadas solo si sus artefactos conservan los hashes. Si cambian los inputs o artefactos registrados, se exige un nuevo directorio de salida.

## Cargar y evaluar el candidato

Después de construirlo:

```powershell
.\scripts\start_hydra.ps1
```

Comprueba el hash, importa el GGUF como `hydra-local`, selecciona `config/models.hydra.yaml` y arranca el gateway local en `127.0.0.1:8080`, con sandbox Docker. Es un arranque local de candidato, no una promoción de producción.

En otra terminal:

```powershell
py -3.12 -m hydra.training.evaluate_corpus --model hydra-local --build-manifest models/hydra-pilot/build-manifest.json --output data/evaluations/hydra-holdout.json
```

Para aceptar una especialización hay que comparar **la misma base 1.5B**, el checkpoint ajustado y su GGUF; el baseline 7B existente no sustituye esa comparación. Además del holdout piloto se necesitan suites de herramientas/JSON, privacidad, memoria y rendimiento. El evaluador conserva `approved=false`: un buen resultado en estas dos familias no aprueba una release.

El evaluador registra el digest del manifiesto Ollama y el hash del blob GGUF. Con `--build-manifest`, rechaza pesos locales alterados o un blob servido distinto del candidato construido. Repite la comprobación al terminar y marca `INVALID_MODEL_IDENTITY` si cambia la identidad observada. Estas comprobaciones en los extremos no detectan una sustitución transitoria que se revierta durante la ejecución; no modificar el alias mientras se evalúa. Los informes se guardan mediante sustitución atómica. La velocidad de generación procede de `eval_count/eval_duration`; no se presenta como TTFT ni como rendimiento integral del motor.

No se han publicado pesos, commits ni releases en GitHub durante esta implementación.
