# Hyd frente a Kev: comparación real y siguiente ronda

5 de octubre de 2026. Hyd equilibrado alcanza **58,25 %** de acierto agregado,
frente a 55,34 % de Hyd congelado y 49,78 % de **Kev HYDRA v2-r1**. Es evidencia
de desarrollo: no demuestra todavía una sustitución segura ni un 90 % de acierto.
No se han cambiado los pesos ni la configuración activa del motor.

## Datos y protocolo

Se conservaron las **5.844 preguntas** del corpus v6, incluidas las del propietario
y las variantes numéricas. Hay tres personas reales, aunque una usa dos cuentas.
Se reservó cada persona por turnos y se entrenó únicamente con las otras dos.
Dentro de esas dos personas se separaron fit, dev, cal_prob y cal_policy por
familias. Hay 5.568 familias en los tres tests reunidos y cada pregunta cuenta
exactamente una vez en cada agregado LOPO. Consentimiento y derechos son
declaraciones de procedencia del corpus, no una verificación jurídica independiente.

SHA-256 del corpus:
`c52e4a5f3fdbef5ea1be74acc6a4087f468dc6fa298ef4c9fc4d9afdfd96908a`.

Los tests ya habían sido inspeccionados en experimentos previos. Además,
la variante equilibrada se propuso tras observar resultados: su mejora necesita
replicación en datos nuevos. No se usaron etiquetas del test en los gradientes,
la selección de regularización, mezcla de memoria, temperatura o umbrales.
No se afirma generalización a toda la población a partir de tres personas.

Encoder Hyd: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`,
revisión `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, 384 dimensiones.
Las cabezas se entrenaron 300 épocas; regularización y memoria se seleccionaron
en dev. La memoria de prototipos solo contiene fit. El nuevo equilibrado iguala
la masa de pesos por clase sin eliminar filas. La temperatura se ajusta en
cal_prob y la política de abstención en cal_policy.

Kev servido realmente: checkpoint local `models/kev-hydra-v2-r1`, adaptador y
cabeza sobre `Qwen/Qwen3.5-0.8B-Base`, revisión
`dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68`. Se verificaron la identidad del
servidor y hashes de pesos/configuración/calibrador. No es una comparación con
Kev original sin adaptar. El calibrador servido usa temperatura 4; una comprobación
separada en las 332 filas humanas cal_prob del primer fold volvió a seleccionar 4.
No se refitó Kev con los otros dos cal_prob. El archivo de entrenamiento declarado
actual de Kev contiene 200 textos distintos y no tiene coincidencias exactas
normalizadas con los tres tests; esto no certifica su historial ni ausencia de
contaminación en el preentrenamiento de su base.

## Resultados emparejados

| Persona reservada | Preguntas | Hyd congelado + memoria | Hyd equilibrado + memoria | Kev v2-r1 |
|---|---:|---:|---:|---:|
| A | 2.598 | 50,58 % | 56,00 % | 63,97 % |
| B | 1.000 | 71,80 % | 75,50 % | 60,20 % |
| C | 2.246 | 53,52 % | 53,16 % | 28,72 % |
| Agregado por pregunta | 5.844 | 55,34 % | **58,25 %** | 49,78 % |

Macro F1 de diez rutas: congelado 0,5589, equilibrado 0,5948 y Kev 0,5400.
La diferencia media por familia equilibrado menos Kev es +9,11 puntos; bootstrap
de 1.000 muestras por familia, semilla 42, intervalo 95 % [+7,43; +10,63] puntos.
Ese intervalo no captura la incertidumbre de tener solo tres personas ni la
selección adaptativa de experimentos. Para congelado: [+4,76; +8,14] puntos.

En A también se contrastaron una cabeza léxica hash (19,78 %) y MiniLM afinado
una época (49,65 %), frente a congelado 50,58 %, equilibrado 56,00 % y Kev 63,97 %.
Una época de afinamiento no mejoró este fold. No se ejecutaron esas dos variantes
en B y C, por lo que no tienen resultado agregado LOPO.

| Ruta crítica: recall agregado | Hyd congelado | Hyd equilibrado | Kev |
|---|---:|---:|---:|
| security | 47,79 % | 59,48 % | 55,06 % |
| privacy | 45,29 % | 61,26 % | 75,13 % |
| high_risk_review | 66,89 % | 65,95 % | 9,19 % |

Equilibrar mejora seguridad y privacidad, pero aún pierde recall de privacidad
frente a Kev. Las tres cabezas equilibradas recargan con paridad; ninguna supera
la política predefinida de confianza en cal_policy. Todos los candidatos siguen
**SHADOW_ONLY**, sin autoridad. El indicador de sustitución permanece false.

### Revisión privacy/abstain comunicada por el usuario

El usuario informa, tras hablar con dos participantes, de posibles casos de
privacidad etiquetados abstain. Es una hipótesis pendiente de revisión, no una
corrección automática ni prueba de que las preguntas sean inválidas.
En los tres folds, Hyd equilibrado predice privacy en 78 originales abstain y
abstain en 35 originales privacy; Kev hace lo mismo en 52 y 55 respectivamente.
Hay **196 preguntas distintas** con alguno de esos desacuerdos. Las predicciones
no permiten decidir quién tiene razón y esa confusión no explica todos los errores.

Se ha preparado un paquete privado de revisión con las **1.316 preguntas** de
ambas clases, incluidas las concordantes, y prioridad para esas 196. El archivo
`review-blind.jsonl` conserva texto e ID, pero oculta etiqueta previa y predicciones.
`auditor-bindings.jsonl` las guarda aparte; MANIFEST fija los hashes y desactiva
entrenamiento. Ninguna etiqueta fue modificada. Ruta local:
`D:\hyd-train-v6\out\review-privacy-abstain-20261005`.

Se reproduce con `python -m hydra.training.decision_label_audit --corpus RUTA`
más un `--comparison RUTA` por cada persona y `--out NUEVO_DIRECTORIO`.
Tras confirmación humana, se creará otra versión manteniendo historial y métricas
de la versión anterior. Reclasificar un test ya observado no crea un test nuevo.

## Confianza y velocidad

Los cortes siguientes son diagnósticos fijados de probabilidad máxima, distintos
de la política del controlador. No son umbrales promovidos tras mirar el test.
En A, Hyd congelado con corte 0,99 acierta 91,40 % de solo 93 casos (3,58 % de
cobertura), con límite inferior Wilson 83,93 %. Kev con corte 0,90 acierta 97,60 %
de 292 casos (11,24 % de cobertura), límite inferior 95,14 %. Esos porcentajes no
equivalen a acertar el 90 % del corpus completo.

GPU local RTX 3060 Ti. Medianas en A: hash 0,63 ms, MiniLM congelado 15,12 ms,
afinado 14,84 ms y Kev 53,97 ms. Hyd se midió dentro del proceso; Kev incluye HTTP
y comprobación de identidad y usa kernels de referencia, sin FLA/causal_conv1d
optimizados. No es un benchmark idéntico de extremo a extremo. Las variantes
reutilizan la inferencia Kev registrada solo si coinciden pesos, calibrador,
test, IDs, hashes de texto, familias y etiquetas; sus tiempos Kev son reutilizados.

## Cambios implementados y comprobación

- `decision_candidates train --class-balance`: equilibrio opcional con metadatos;
  las rondas admiten `class_balance: true`. El valor predeterminado sigue false.
- `decision_compare --kev-cache`: reutilización estricta de una comparación real
  completa, progreso persistente y rechazo de evidencia incompleta o alterada.
- `scripts.report_hyd_kev_comparison`: exportación exclusivamente agregada con
  hashes, métricas por clase, intervalos por familia y diagnósticos de confianza.
  No exporta preguntas, nombres, IDs de participantes ni pesos del modelo.
- Prueba de aislamiento: cambiar solo etiquetas de test deja idéntica la cabeza
  entrenada. Pruebas de caché y exportación rechazan bindings incorrectos.

Suites completas ejecutadas durante esta revisión: HYDRA 1.150 passed / 83 skipped;
Hyd 1.246 passed / 87 skipped. Tras añadir el equilibrio y la revisión, las 22 pruebas afectadas
pasaron y Ruff no detectó errores en los archivos cambiados. Las fixtures sintéticas
comprueban contratos; las cifras de arriba proceden de inferencias reales del corpus.

Evidencia exportable:
[agregado completo](evidence/hyd-kev-comparison-balanced-2026-10-05.json).
Los artefactos privados completos permanecen fuera de Git en
`D:\hyd-train-v6\out\continuous-20261005`.

## Siguiente plan medible

1. Reservar antes de inspeccionar una colección nueva de varias personas y escenarios;
   conservar variantes y etiquetar las familias. Separar también casos de otras
   lenguas, herramientas reales y entradas multimodales. No retocar el test después
   de comparar resultados.
2. Revisar con personas las fronteras privacy/security/tool_use/high_risk_review.
   Guardar originales y eventos de corrección. Completar subtipos E3 y negativos;
   sin negativos no se calcula una tasa fiable de falsas alarmas.
3. Comparar equilibrado, sin equilibrar y afinamientos de 1–3 épocas con selección
   solo en dev. Calibrar cada candidato en cal_prob y fijar abstención en cal_policy.
   Variar una receta por ronda, registrar presupuesto y detener entrenamiento
   cuando dev deje de mejorar. Las propuestas sintéticas requieren revisión humana.
4. Ejecutar una comparación emparejada única en el test nuevo con checkpoint Kev
   fijado. Exigir mejora global, ausencia de regresión crítica y límites inferiores
   de precisión junto a cobertura y falsos positivos. Para el objetivo 90 %, fijar
   antes si se refiere a todas las preguntas o a decisiones aceptadas y su cobertura.
5. Solo después de superar criterios y aprobación humana, preparar integración con
   observación paralela, canario y reversión al checkpoint anterior. La memoria
   persistente aporta experiencias verificadas; no convierte predicciones en etiquetas.

Las rondas y sus exportaciones siguen funcionando localmente sin depender de Lovable.
La activación de escritura PostgreSQL sigue pendiente de una migración revisada;
la conexión de solo lectura ya verificada no implica que exista ese esquema.
