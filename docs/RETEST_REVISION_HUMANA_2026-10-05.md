# Resultado tras las correcciones humanas

5 de octubre de 2026. Se importaron **629 revisiones confirmadas**: 387 cambios
de etiqueta y 242 confirmaciones. No se modificaron los textos, IDs, autores,
familias, consentimiento ni derechos declarados. Se conservaron las 5.844 filas.
La exportación corresponde a cinco nombres de revisor declarados localmente;
el corpus sigue teniendo tres autores reales. No son cinco autores nuevos.

El archivo recibido tiene SHA-256
`5f3f05eb3cd5e1c8af1ff907d77d5b02c45ec0dc82f871b44eacea4b349bf82c`.
Todos sus eventos coinciden con texto, hash y versión de corpus; no hay IDs
duplicados, confirmaciones ausentes ni etiquetas ambiguas. Los 196 casos
prioritarios están revisados. Se revisó el 47,80 % de la cola de 1.316 preguntas;
**quedan 687**. En el corpus completo quedan 5.215 filas sin esta nueva revisión.

Cambios principales: abstain→security 144, abstain→privacy 79, abstain→chat 30,
privacy→research 28 y privacy→security 25. Las decisiones humanas se admitieron
tal como fueron confirmadas; no se sustituyeron por sugerencias de los modelos.
Ahora hay 16 familias con etiquetas diferentes entre sus variantes. Esto puede
reflejar cambios legítimos de intención: se señala para revisión, sin borrar,
invalidar ni uniformar esas preguntas automáticamente.

## Separar revisión de etiquetas y aprendizaje

Se repitieron las mismas tres particiones por autor y familia, con fit/dev/cal_prob/
cal_policy/test separados, 300 épocas, semilla 42 y el mismo MiniLM fijado por
revisión. Se entrenaron seis cabezas nuevas: congelada y equilibrada en cada fold.
Los números siguientes son agregados por pregunta sobre 5.844 decisiones.

| Evaluación | Hyd congelado | Hyd equilibrado | Kev HYDRA v2-r1 |
|---|---:|---:|---:|
| Modelos anteriores, etiquetas originales | 55,34 % | 58,25 % | 49,78 % |
| Los mismos modelos, etiquetas revisadas | 53,35 % | **56,50 %** | 48,37 % |
| Hyd adestrado de nuevo, etiquetas revisadas | 53,83 % | **56,38 %** | 48,37 % |

Con las mismas etiquetas revisadas, el entrenamiento cambia +0,48 puntos en
congelado y −0,12 puntos en equilibrado. No hay evidencia aquí de una mejora
general clara por volver a entrenar. La comparación correcta del nuevo candidato
es contra 56,50 % del anterior reevaluado, no contra 58,25 % de otra versión de
etiquetas. Corregir los datos no garantiza que suba la puntuación inmediatamente.

| Autor reservado | Preguntas | Nuevo Hyd congelado | Nuevo Hyd equilibrado | Kev |
|---|---:|---:|---:|---:|
| A | 2.598 | 51,19 % | 54,97 % | 61,16 % |
| B | 1.000 | 70,30 % | 73,40 % | 60,00 % |
| C | 2.246 | 49,55 % | 50,45 % | 28,41 % |

Macro F1 agregado del equilibrado nuevo: 0,5766; Kev: 0,5227
(la cifra exacta está en la evidencia JSON). La ventaja media por familia del
nuevo equilibrado sobre Kev tiene intervalo bootstrap 95 % [+6,91; +9,99] puntos.
El bootstrap usa familias, no personas; tres personas no certifican generalización
a la población. Las correcciones y estos tests ya fueron inspeccionados: sigue
siendo desarrollo parcialmente revisado, no un test nuevo ciego.

## Rutas críticas y criterios de promoción

| Recall agregado, etiquetas revisadas | Nuevo Hyd equilibrado | Kev |
|---|---:|---:|
| privacy | 64,77 % | 68,29 % |
| security | 52,89 % | 46,03 % |
| abstain | 38,28 % | 50,47 % |
| high_risk_review | 65,59 % | 9,14 % |

Hyd sigue ganando en acierto global en estas pruebas, pero pierde en privacy y
abstain. Las seis cabezas recargan con paridad y ninguna supera la política
predefinida de confianza/cobertura en cal_policy. No se promocionó ningún modelo;
todos permanecen **SHADOW_ONLY** y el objetivo del 90 % sigue pendiente.

Para Kev se reutilizaron las inferencias reales registradas anteriormente, con
textos idénticos, pesos y calibrador comprobados por SHA. Solo se cambió la
etiqueta usada para puntuar. No se lanzó un nuevo servidor Kev ni se midieron
latencias nuevas; no se presenta esa reutilización como nueva inferencia o entrenamiento.

## Artefactos y comprobaciones

El importador `hydra.training.decision_review_import` valida confirmación, revisor,
etiqueta, fecha con zona horaria, SHA de origen y texto original antes de escribir
un directorio nuevo. Conserva todos los eventos; una corrección posterior se
resuelve por fecha, sin borrar historia. Una etiqueta ambigua conserva el original
con marca pendiente y bloquea este ciclo de entrenamiento hasta adjudicarla.

`scripts.retest_human_reviews` distingue la reevaluación de modelos anteriores
del entrenamiento nuevo y publica solo agregados. Verifica los pesos/calibrador
Kev y que las preguntas y autores no cambiaron. No reutiliza como válida una
comparación con otra versión de texto ni cambia los artefactos de la versión anterior.

Artefactos privados locales:

- `D:\hyd-train-v6\out\reviewed-corpus-20261005\corpus_reviewed.jsonl`.
- `D:\hyd-train-v6\out\reviewed-corpus-20261005\human-review-events.jsonl`.
- `D:\hyd-train-v6\out\retest-reviewed-v2-20261005`: seis cabezas, particiones e informe.

[Evidencia agregada exportable](evidence/hyd-human-review-retest-2026-10-05.json)
y [manifiesto sin textos ni revisores](evidence/hyd-human-review-import-2026-10-05.json).
Los corpus, eventos individuales y pesos no se subieron a Git.

Pasaron las 30 pruebas afectadas, incluidos rechazo de texto/origen alterado,
persistencia de revisión, versionado sin cambiar autores, selección por fecha,
confianza pendiente y conservación de probabilidades al cambiar solo la etiqueta.
Ruff y git diff --check pasaron. Las fixtures son sintéticas; las métricas anteriores
proceden del corpus y de las seis ejecuciones reales de entrenamiento.

## Próximo paso

Terminar las 687 revisiones pendientes manteniendo originales y nuevas decisiones,
revisar las fronteras privacy/security/abstain/tool_use y las 16 familias mixtas.
Después reservar preguntas nuevas de más autores antes de inspeccionarlas. En dev,
comparar recetas de afinamiento y memoria con criterio fijo; cal_prob ajusta
probabilidades y cal_policy fija abstención. Solo tras una comparación independiente,
ausencia de regresión crítica y aprobación humana se plantea sustituir Kev.
