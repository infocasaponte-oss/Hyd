# Auditoría del 1.5B y ampliación del corpus

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

El candidato v3 es Qwen2.5-Coder-1.5B-Instruct con adaptación LoRA, 1.543.714.304 parámetros y un GGUF Q5_K_M de 1.125.049.920 bytes. Su SHA256 es `42c8561667bc935ae100b649b658f3b55895304c8def0303866e79bf2a940e0d`. Se verificaron hashes de entrenamiento, adaptador, fusión, conversión y cuantización. Es un modelo textual: no tiene una torre visual.

La evidencia anterior muestra 64/64 en código conocido, 34/48 en el diagnóstico con instrucción JSON explícita y 24/48 en el contrato original ambiguo. Estos resultados no certifican un 90% general. El corpus v3 tenía 384 ejemplos de entrenamiento, centrados en copia literal, JSON y repetición de tareas de código. La pérdida baja de entrenamiento no sustituye la evaluación de tareas nuevas.

## Corpus v4

`data/hydra-instruction-v4` contiene 500 instrucciones sintéticas distintas: 50 por tarea de copia, JSON tipado, extracción, suma, ordenación, minúsculas, recuento, abstención por falta de datos, protección de datos privados y respuesta basada en evidencia suministrada. No son 500 ejemplos humanos y no se presentan como tales.

Particiones por familia de redacción, evitando compartir la misma plantilla entre entrenamiento y evaluación:

| Partición | Nuevas paráfrasis | Código anterior | Total |
| --- | ---: | ---: | ---: |
| Entrenamiento | 300 | 192 | 492 |
| Desarrollo | 100 | 0 | 100 |
| Calibración | 100 | 0 | 100 |
| Regresión congelada anterior | 0 | 0 | 48 |

Se rechazan repeticiones tras normalizar Unicode, espacios y mayúsculas. La separación de redacciones reduce filtraciones, pero las operaciones y vocabulario siguen relacionados: la novedad de una cadena no implica independencia semántica. El test anterior se copia byte a byte y conserva su hash. No se entrena con sus respuestas. Los 692 ejemplos no congelados ocupan como máximo 161 tokens, por debajo del límite 512: no se trunca ninguna respuesta.

La receta `config/recipes/hydra-instruction-v4.json` usa tres épocas, LoRA 16, tasa 0,00005, cuatro proyecciones de atención y CUDA obligatorio. Genera un candidato nuevo en `models/hydra-instruction-v4`, sin reemplazar v3 ni CeltIA. El constructor comprueba también el hash de la partición de calibración.

## Qué se calibra

1. **Confianza de clasificación**: ajustar probabilidades frente a etiquetas verificadas, con calibración separada de entrenamiento y selección. Medir NLL, Brier, ECE y precisión antes/después. La temperatura escalar conserva el orden de las clases; no corrige una clase equivocada. [Guo et al., ICML 2017](https://arxiv.org/abs/1706.04599).
2. **Fiabilidad de respuestas**: comprobar salidas generadas contra resultados verificables, contabilizar aciertos por familia y dar intervalos Wilson del 95%. No convertir automáticamente probabilidad de tokens en probabilidad de verdad. `hydra/training/generation_reliability.py` realiza esta medición sobre el GGUF identificado por hash, con generación determinista y tipos JSON estrictos. Diez aciertos de diez en una familia siguen dando un límite inferior aproximadamente 0,72.
3. **Cuantización**: calibrar escalas de activaciones/pesos en PTQ, distinto de calibrar confianza. NVIDIA documenta un flujo con un conjunto representativo; no se reutiliza el test congelado. Esta ronda mantiene Q5_K_M y no declara haber ejecutado AWQ, GPTQ o ModelOpt. [NVIDIA Model Optimizer](https://github.com/NVIDIA/Model-Optimizer/blob/main/examples/hf_ptq/README.md).

## Métodos investigados para vLLM

| Método | Uso y decisión en HYDRA |
| --- | --- |
| Temperatura escalar | Primera opción por su único parámetro; implementada con búsqueda continua acotada por NLL. |
| Dirichlet | Puede ajustar sesgos entre clases; evaluar cuando haya más calibración por clase. Tiene más parámetros y debe compararse en desarrollo separado. [Kull et al., NeurIPS 2019](https://arxiv.org/abs/1910.12656). |
| Conformal | Proporciona conjuntos de respuestas o abstención bajo sus supuestos; no garantiza que cualquier texto sea cierto ni elimina cambios de distribución. Investigación para un paso posterior. [Conformal Language Modeling](https://arxiv.org/abs/2306.10193). |
| PTQ con corpus representativo | Orientado a conservar calidad al reducir precisión; medir regresión del artefacto cuantizado final y recalibrar su confianza. |

La temperatura de `SamplingParams` controla la generación; no equivale por sí sola a una temperatura de calibración elegida con etiquetas. Las distribuciones top-k parciales no se normalizan como si contuvieran todo el vocabulario. [Referencia oficial de SamplingParams](https://docs.vllm.ai/en/latest/api/vllm/sampling_params/).

## Implementación para vLLM

`scripts/collect_vllm_candidate_scores.py` puntúa mediante teacher forcing todas las continuaciones declaradas, incluido EOS, con `prompt_logprobs=0` y `logprobs_mode=raw_logprobs`. Valida la frontera de tokenización y rechaza tokens ausentes. La entrada es JSONL con `id`, `split` (`calibration` o `validation`), `prompt` y `expected`; las etiquetas completas se pasan mediante `--labels`. Usa el modelo fusionado en safetensors.

`hydra/training/vllm_calibration.py` ajusta la temperatura exclusivamente sobre filas `calibration`, exige el conjunto completo de etiquetas y valores finitos, rechaza test y modos procesados, vincula pesos/tokenizador/backend/cuantización mediante huellas y permite evaluar filas `validation` con IDs disjuntos. La confianza es condicional al conjunto declarado de candidatos, no una medida de verdad de texto libre. El artefacto no concede autoridad al router ni se carga automáticamente en producción.

```text
python -m scripts.collect_vllm_candidate_scores --model models/hydra-instruction-v4/merged --dataset data/router-calibration.jsonl --labels chat coding reasoning research vision tool_use abstain security privacy high_risk_review --output runtime/vllm-calibration-scores-v1.jsonl
python -m hydra.training.vllm_calibration --scores runtime/vllm-calibration-scores-v1.jsonl --identity runtime/vllm-calibration-scores-v1.identity.json --labels chat coding reasoning research vision tool_use abstain security privacy high_risk_review --output models/vllm-router-calibrator-v1.json
```

Estas rutas de entrada son ejemplos: el dataset de clasificación debe existir y estar verificado; no se finge que las 500 tareas generativas sean un corpus de clasificación. El colector vLLM está preparado, pero no se ha ejecutado aquí contra una instalación real. vLLM no admite Windows de forma nativa; requiere Linux/WSL o una alternativa compatible. Su soporte GGUF oficial se describe como experimental, por lo que para esa validación se propone el modelo fusionado safetensors, conservando Ollama para la validación real del GGUF. [Requisitos oficiales](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/), [soporte GGUF](https://docs.vllm.ai/en/latest/features/quantization/gguf/).

## Pruebas y reproducción

```text
python -m hydra.training.instruction_corpus_v4
python -m scripts.train_instruction_v2_when_free --recipe config/recipes/hydra-instruction-v4.json
python -m scripts.register_instruction_candidate --version 4
python -m scripts.validate_instruction_v4
```

El generador no sobrescribe corpus existentes. El validador compara v3 y v4 sobre los 100 casos de desarrollo, mide los 100 casos de calibración de v4, ejecuta la regresión congelada de instrucciones y las 64 tareas de código en sandbox. Persiste evidencia por caso. No utiliza esas métricas para entrenar y no promociona automáticamente.

El acceso web de Studio continúa separado del corpus: leer una página no incorpora automáticamente sus textos al entrenamiento. `HYDRA_PUBLIC_WEB_ENABLED=true` requiere offline desactivado. CeltIA permanece sin cambios.

## Resultado real completado

Entrenamiento en RTX 3060 Ti: 699,44 segundos, pico de memoria asignada 3.481.800.704 bytes, pérdida de entrenamiento 0,02879 y de validación 0,00748. El GGUF v4 Q5_K_M se creó y registró como `hydra-instruction-v4:latest`, SHA256 `3f3d21cf139024c1c3b206ad8c5ec994574fd5fa33738bee4aeb43614b6b0388`, tamaño 1.125.049.920 bytes. La auditoría verificó cuatro etapas y 740 prompts únicos entre todas las particiones.

| Evaluación | v3 | v4 |
| --- | ---: | ---: |
| Desarrollo nuevo, 100 casos | 65/100 | 99/100 |
| Calibración nueva, 100 casos | No ejecutada | 98/100 |
| Regresión original de instrucciones | 24/48 | 24/48 |
| Código congelado en sandbox | 64/64 | 64/64 |

Intervalo Wilson del 95% para v4: desarrollo [0,9455; 0,9982], calibración [0,9300; 0,9945]. Son intervalos sobre tareas sintéticas relacionadas, no cobertura del mundo real. Los tres errores nuevos están en ordenación numérica: desarrollo 9/10 y calibración 8/10. El contrato antiguo no mejoró. No se retocaron ni se añadieron al entrenamiento estos casos después de observar sus resultados. Próximo paso: nuevos ejemplos contrastivos de ordenación en desarrollo, sin modificar esta calibración ni los tests congelados, y prueba humana independiente.

La medición empírica se guarda en `docs/evidence/instruction-v4-generation-calibration.json`; no asigna automáticamente 98% de confianza a cada respuesta ni cambia permisos del motor. La comparación está en `instruction-v4-summary.json`; las auditorías en `instruction-v3-audit-2026-09-30.json` y `instruction-v4-audit-2026-09-30.json`. Pasaron 22 pruebas enfocadas y el análisis Ruff de los módulos nuevos. v4 sigue sin promoción y Kev conserva sus restricciones de autoridad.

Para iniciar un Studio separado con v4: `python -m scripts.run_studio_candidate --version 4 --port 18085`. El perfil por defecto y el Studio 18084 siguen siendo v3. El modelo puede probarse directamente con `ollama run hydra-instruction-v4`.

El Studio experimental v4 está iniciado en `http://127.0.0.1:18085/studio`. Kev fue restaurado en GPU en el puerto 8009. Una primera petición por el motor pidió solo JSON y recibió explicación adicional, pese a los buenos resultados aislados. Se corrigió el worker de razonamiento para solicitar generación JSON estructurada únicamente ante una instrucción explícita y un perfil con soporte nativo; no se eliminan textos después de generar ni se impone una estructura inventada. La repetición real respondió solo `{"id":43,"activo":false}`, HTTP 200, modelo `hydra-instruction-v4-candidate`, 679 ms. Evidencia antes/después: `studio-v4-chat-before-json-fix.json` y `studio-v4-chat-live.json`. Esto verifica formato y tipos en esa llamada, no certifica toda generación; conserva `verified=false`.

Después de corregir el formato del motor, pasaron 43 pruebas enfocadas, incluyendo ejecución del worker con perfiles tipados que soportan y no soportan JSON nativo, pruebas del kernel e integridad del corpus. Ruff y `git diff --check` también pasaron. El antiguo 18084 necesita reinicio para recoger cambios de código; el nuevo 18085 los está ejecutando.
