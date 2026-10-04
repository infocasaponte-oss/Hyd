# Adiestramiento HYDRA 1.5B y Kev: resultados reales

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Estado: candidatos experimentales. No hay certificación ni promoción automática.

Verificación del código tras los cambios: 519 pruebas superadas y 5 omitidas en 300,53 segundos. También se verificó HTTP 200 del Studio experimental y ejecución CUDA del checkpoint Kev servido.

## HYDRA 1.5B

Se generaron dos candidatos diferentes sin sustituir los modelos de producción. El candidato v3 parte de Qwen2.5-Coder-1.5B-Instruct fijado por revisión y SHA256; usa LoRA r16 en q/k/v/o, tres épocas y 384 ejemplos de entrenamiento. Las respuestas de prueba no se incorporaron al entrenamiento.

- Entrenamiento CUDA: 511,96 segundos, pico de memoria asignada de 3.333.349.376 bytes.
- Artefacto Q5_K_M: `D:\HYDRA\models\hydra-instruction-v3\HYDRA.gguf`.
- SHA256: `42c8561667bc935ae100b649b658f3b55895304c8def0303866e79bf2a940e0d`.
- Alias Ollama separado: `hydra-instruction-v3:latest`.
- Programación: 64/64 casos de regresión superados mediante ejecución en sandbox Docker. El candidato v2 obtuvo 51/64 en el mismo panel.
- Instrucciones/JSON con tipos explícitos: 34/48 (70,83%); v2 obtuvo 24/48.
- Panel original: 24/48. Ese panel contiene ambigüedad entre cadenas sí/no y booleanos; se conservó intacto y se creó un diagnóstico separado. Ninguno constituye certificación humana independiente.

La limitación principal sigue siendo la generalización de instrucciones y tipos JSON; el 100% de programación se refiere únicamente a estas 64 tareas sintéticas.

## Kev entrenado

Se completó un ajuste separado del checkpoint `jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e`, con base `Qwen/Qwen3.5-0.8B-Base@dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68`. El primer intento se interrumpió porque la CLI elegía otra base por defecto; se preservó y se corrigieron explícitamente base, revisión, rango LoRA y dimensión de cabeza en el nuevo intento.

Checkpoint terminado: `D:\HYDRA\models\kev-hydra-v2-r1`.

- Corpus revisado: 200 textos únicos de diez etiquetas tras deduplicar los 1000 registros. Procedencia: plantillas sintéticas revisadas, no 1000 textos humanos independientes.
- Entrenamiento CUDA/bf16: 200 registros, 50 pasos, 245,64 segundos; cero registros rechazados o truncados. Pico CUDA: 1.805.051.392 bytes.
- Salidas admitidas: chat, coding, reasoning, research, vision, tool_use, abstain, security, privacy y high_risk_review.
- Calibración: 200 ejemplos separados; temperatura 4, vinculada al checkpoint. Test: las 100 paráfrasis conocidas, sin entrenamiento sobre sus respuestas.
- Regresión: 77/100; cobertura válida 100%; ECE 0,03776; límite inferior Wilson 95%: 0,67845.
- Estabilidad CUDA: 30 llamadas sobre diez categorías, tres repeticiones por categoría; diez decisiones estables, deriva de probabilidades cero, latencia mediana 41,45 ms y máxima 238,14 ms. Esto mide repetibilidad, no precisión adicional.

| Etiqueta | Aciertos sobre 10 |
| --- | ---: |
| chat | 10 |
| coding | 10 |
| reasoning | 10 |
| research | 10 |
| vision | 8 |
| tool_use | 4 |
| abstain | 5 |
| security | 9 |
| privacy | 8 |
| high_risk_review | 3 |

Kev devuelve decisiones tipadas, no texto libre. La composición verificada usa Kev para clasificar y el GGUF 1.5B para generar la respuesta. Se comprobó una consulta completa en 447 ms con ambas inferencias reales, sin caché.

## Integración y límites

El contrato completo comparte exactamente los mismos criterios entre corpus, calibración y observador. El observador comprueba que el servidor sigue cargando el checkpoint al que pertenece el calibrador.

Se añadió una puerta de autoridad que exige evaluación independiente completa, precisión mayor del 90%, límite inferior Wilson de al menos 90%, cobertura mínima del 80% y ECE máximo 0,10. Evidencia inválida, NaN, infinitos o checkpoint sustituido no habilitan control. Incluso con esa puerta superada, las decisiones críticas y la autorización de herramientas quedan bajo política determinista.

Actualmente Kev está en observación. No ha sido promocionado. El perfil experimental no tiene modelo visual y no sustituye al Studio anterior ni a CeltIA.

## Prueba local

Studio del candidato: `http://127.0.0.1:18084/studio`.

Para volver a arrancar los procesos, desde `D:\HYDRA`, en dos terminales:

```powershell
runtime/kev-env/Scripts/python.exe -m scripts.serve_kev_candidate --run models/kev-hydra-v2-r1 --port 8009
.venv/Scripts/python.exe -m scripts.run_studio_candidate --port 18084
```

Prueba reproducible de la composición:

```powershell
.venv/Scripts/python.exe -m scripts.query_kev_hydra_candidate --version 3 --checkpoint models/kev-hydra-v2-r1
```

Los ajustes de compatibilidad Windows están fuera del checkout upstream de Kev y preservan bloqueos entre procesos reales. Su código de inferencia y entrenamiento no se modificó.

## Siguiente ronda antes de escalar

1. Ampliar desarrollo con situaciones diversas de acciones frente a análisis, entrada incompleta y autorización irreversible; revisar las etiquetas sin copiar las respuestas del test conocido.
2. Añadir currículo de tipos y formatos estructurados, con validación de desarrollo explícita y replay de programación. Seleccionar hiperparámetros por desarrollo, nunca por el test de certificación.
3. Congelar un nuevo test humano independiente y su SHA256 antes de ejecutar candidatos. Las 100 paráfrasis actuales quedan como regresión conocida.
4. Reentrenar Kev, volver a calibrar únicamente en una partición separada y ejecutar estabilidad, seguridad y latencia además de precisión. No reducir los umbrales para aprobarlo.
5. Con la RTX 3060 Ti de 8 GiB, medir primero un candidato 3B Q5 con contexto limitado y residencia junto a Kev. Un 8B visual necesita gestión de carga y descarga; no asumir que cabe simultáneamente con todos los motores ni certificarlo por su tamaño.

## Evidencia

- `docs/evidence/instruction-v3-contract-diagnostic.json`
- `docs/evidence/instruction-v3-original-contract.json`
- `docs/evidence/instruction-v3-coding-regression.json`
- `docs/evidence/kev-hydra-v2-r1-regression.json`
- `docs/evidence/kev-hydra-v3-composed-2026-09-30.json`
- `docs/evidence/kev-hydra-v2-r1-stability.json`
- Manifiestos y métricas locales de ambos checkpoints en `models/`.
