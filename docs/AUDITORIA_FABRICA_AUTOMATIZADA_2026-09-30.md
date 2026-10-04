# Auditoría y plan de fábrica automatizada HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 30 de septiembre de 2026. Repositorio: infocasaponte-oss/HYDRA-SO.

## Alcance y límites

Inventario del 100% de los 616 archivos versionados locales, hashes y análisis sintáctico de todos los Python en `docs/evidence/repository-audit-2026-09-30.json`. Ningún error sintáctico encontrado. Esto NO equivale a revisar semánticamente cada línea ni certificar seguridad, rendimiento o producción. Los binarios ignorados, servicios externos y ramas remotas requieren verificaciones separadas. Referencias remotas consultadas mediante `git ls-remote`: main d1011d86cbce981095118b98e15d1ea94185def3; integration/hydra-1.0 2effc5e2b52ff06127f5be8fe016685ebc9229ec. No se ha auditado el contenido completo de esas referencias remotas.

## Hallazgos prioritarios comprobados

1. **P0: promoción no acreditada.** El histórico de trabajo muestra ajustes del híbrido después de inspeccionar errores del test. El 96% es regresión sobre un conjunto reutilizado, no prueba independiente. `promotion.json` declara PROMOTED con solo accuracy. Requiere reclasificación como candidato y nuevo holdout ciego; no autoriza decisiones críticas.
2. **P0: calibración ajena.** El manifiesto referencia `kev-calibrator-v3.json`, pero `HybridClassifier` devuelve confianzas constantes y no aplica ese calibrador. No hay evidencia de calibración del híbrido.
3. **P0: desarrollo duplicado.** `human-dev-v2.jsonl` tiene 1.000 filas pero solo 200 textos distintos. El generador combina cuatro patrones y cinco temas por clase. La aprobación del usuario acredita revisión, no autoría humana ni diversidad independiente.
4. **P0: regeneración destructiva del corpus revisado.** `train_decision_v4.py` llama a `build()` antes de entrenar, sobrescribiendo potencialmente correcciones humanas y metadatos. La revisión registrada no está ligada al hash del fichero aprobado.
5. **P0: incompatibilidad de características.** `specialists.py` añadió caracteres globalmente sin versionar el extractor del artefacto; pesos anteriores pueden cargarse con rasgos distintos a los de entrenamiento.
6. **P1: integración incompleta.** No se encontraron referencias al híbrido en core/router. Su manifiesto de promoción no demuestra activación en el runtime.
7. **P1: receta no ejecutable como contrato único.** `hydra-decision-v4.yaml` declara cinco etiquetas (answer/review), mientras el entrenamiento usa diez (chat/high_risk_review, etc.); omite dev-v2 y el script no consume esta receta.
8. **P1: validación contaminable en SFT.** `TRL_SFT_SCRIPT` usa train como validation si falta validación. El pipeline debe bloquear esta situación.
9. **P1: promoción débil en TrainingLab.** La validación genérica admite accuracy >=0,7. Es insuficiente para routers críticos y no equivale al objetivo >0,9.
10. **P1: arquitectura duplicada.** Existen core/kernel y runtime/kernel, corpus/factory y runtime/dataset_factory, model_factory y runtime/model_factory. Designar autoridad única y probar puentes para impedir promociones contradictorias.
11. **P1: perfiles no son motores independientes.** fast/deep/judge comparten qwen3:8b. Scores de capacidades son priors declarados, no resultados medidos. Vision con gemma4:26b falló por OOM en la prueba anterior.
12. **P1: GGUF y configuración son distintos.** hydra-q5-v2 modifica sistema y parámetros de Ollama sobre el mismo GGUF Q5; no acredita nuevos pesos, mejor precisión ni multimodalidad del GGUF.

## Diseño objetivo

Una ejecución reproducible y reanudable:

`INGEST -> QUARANTINE -> CURATE -> FREEZE_DATASET -> PREFLIGHT -> TRAIN -> CALIBRATE -> EVALUATE -> MERGE -> EXPORT_GGUF -> BENCHMARK -> SHADOW -> CANARY -> ACTIVE`

Cualquier gate fallido produce REJECTED con causas y evidencias. Cada etapa tiene clave idempotente, entradas por hash, salidas inmutables, checkpoint, tiempos, recursos y versión de herramientas. Prohibir cambios directos de JSON a ACTIVE. Reutilizar TrainingLab, ArtifactStore, CorpusStore, DatasetFactory, ModelFactory y DeploymentController; añadir coordinador persistente, no otro framework de agentes.

Separar productos: HYDRA Decision (clasificador/política), HYDRA Text (pesos y GGUF), HYDRA Vision (VLM y proyector), HYDRA Engine (software que los coordina). Un GGUF no contiene por sí solo permisos, memoria, herramientas o todo el motor.

## Corpus completo para el producto definido

No existe corpus universal 100% completo. Definir cobertura verificable de requisitos: idioma, dominio, dificultad, riesgo, modalidad, contexto y herramientas. Publicar matriz con cada celda requerida, cuota, fuente, revisión y benchmark asociado; declarar incompletas las celdas vacías.

Registro canónico: id; family_id; tenant; origen; licencia y permiso de entrenamiento; hash de contenido; modalidad y hashes de adjuntos; idioma; tarea; dificultad; riesgo; entrada; respuesta objetivo; verificador; evidencia; autoría humana/sintética; revisión vinculada al hash; fecha; partición. Quarantena para derechos desconocidos, secretos, errores y datos sin verificación.

Familias: conversación e instrucciones; programación con pruebas aisladas; matemáticas con verificadores; investigación con fuentes fechadas; decisiones y abstención; privacidad/seguridad; uso de herramientas con permisos; traducción; contexto largo; visión/OCR; planificación y recuperación de errores. Generar preferencias DPO solo después de SFT medido.

Arranque propuesto: 1.000 decisiones realmente únicas y revisadas; 10.000 ejemplos SFT verificados; 1.000 casos independientes de decisión; 300 casos de generación verificables; 200 casos de visión; 100 casos adversariales por área crítica. Son objetivos de adquisición, no datos ya disponibles ni garantía de calidad.

Dividir por familia/fuente/periodo ANTES de parafrasear. Mantener train, development, calibration y blind_test separados; deduplicación exacta y semántica entre particiones. El antiguo test de 100 pasa a regression: ya fue observado. Blind test administrado por persona distinta del ajuste, con presupuesto de consultas y nueva versión cuando se exponga.

## Plan implementable y criterios de cierre

| Fase | Entregable | Criterio verificable |
|---|---|---|
| P0 saneamiento | invalidar promoción no independiente; versionar extractor; proteger corpus revisado; hashes de revisión | test negativo impide promoción con evidencia contaminada o calibrador ajeno |
| P1 contrato | receta tipada única con clases, fuentes, hardware, gates y presupuesto | validación rechaza aliases incoherentes, particiones ausentes o train usado como validation |
| P2 corpus | ingesta/curación/dedupe/cobertura y releases inmutables | cero solapamiento de familias; 100% de ejemplos admitidos con derechos y procedencia |
| P3 entrenamiento | CPU para clasificador; LoRA/QLoRA CUDA para generador; checkpoint/reanudación | versión base y librerías fijadas; semilla; GPU y memoria registradas; reproducibilidad de inputs |
| P4 calibración | calibrador nuevo por artefacto y esquema de clases; umbral de abstención | fit exclusivamente en calibration; hash modelo/dataset; medir ECE/Brier y cobertura |
| P5 calidad | evaluator independiente + regression + adversarial | accuracy >90% global y resultados por clase; límites de errores críticos y cobertura fijados previamente |
| P6 GGUF | merge adapter/base; F16; quant Q4/Q5; identidad y model card | GGUF parseable; licencia; comparación F16 vs quant en mismo benchmark; no sobrescribir baseline |
| P7 operación | benchmark real GPU/RAM/VRAM, cold/warm, contexto y concurrencia | sin OOM ni errores sostenidos; p50/p95 y presupuestos medidos, no priors |
| P8 despliegue | shadow -> canary 5/20/100%; rollback por gates | evidencia real del nuevo artefacto; registro activo único; prueba CeltIA -> HYDRA -> modelo |
| P9 continuidad | captura autorizada, drift, cola de revisión, retraining por evento | datos de producción en cuarentena; ninguna autoaprobación; holdout inmutable y rollback probado |

Para decisión: proponer ECE <=0,10, Brier <=0,15 y cobertura >=0,80; validar estos límites antes de fijarlos. Reportar intervalo de confianza además del porcentaje: 90/100 no demuestra precisión poblacional >90%. Las clases críticas requieren revisión y gates específicos aun si supera accuracy global. Reglas deterministas no equivalen a probabilidades calibradas.

## Automatización y recursos

Jobs persistentes con leases, heartbeat, reintentos limitados y cancelación. Un solo entrenamiento/inferencia grande por GPU; medir memoria libre antes de reservar. Presupuesto en horas, VRAM, disco y tamaño de descarga; no reiniciar tras OOM sin cambiar receta. Elegir VLM pequeño tras preflight, no asumir que 26B cabe en RTX 3060 Ti. Desacoplar simulación/offline y evidencia real.

Disparadores: release de corpus aprobado, cambio de receta, degradación de métrica confirmada o nueva base admitida. No entrenar continuamente sobre respuestas sin verificar. Cada ejecución debe poder iniciarse desde CLI/API y observarse en Studio con artefactos, métricas y razón de rechazo.

La release final debe contener engine package, config validada, modelo/base/adaptador/GGUF hashes, proyector visual si corresponde, dataset cards, licencias, extractor/calibrador versionados, evaluación independiente y scripts de inicio. CeltIA debe consumir un puerto dedicado verificado por identidad de /health y no confundirlo con su propio servidor; .env.local tiene precedencia sobre .env.

## Verificación pendiente

Suite completa ejecutada: **483 passed, 5 skipped en 186,15 segundos** con `python -m pytest -q --disable-warnings --maxfail=5`. Las pruebas omitidas no acreditan sus integraciones. Falta revisión semántica archivo por archivo, auditoría de dependencias y secretos, comparación completa de ramas remotas y pruebas físicas sostenidas de todos los backends. No presentar el inventario del 100% como certificación integral ya terminada.
