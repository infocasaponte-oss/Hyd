# Auditoría de la revisión humana de HYDRA v7

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 2026-10-01. Archivo auditado: `C:\Users\mejil\Downloads\hydra-mi-revision.json`.

## Resultado

El archivo es estructuralmente válido y coincide con las valoraciones guardadas en Studio. Las valoraciones están vinculadas al GGUF v7 y al conjunto de evaluación correctos. Se han revisado las **287 preguntas únicas**; los 300 registros originales incluyen 13 repeticiones excluidas del cálculo.

| Valoración presentada | Casos |
| --- | ---: |
| Correcta | 234 |
| Incorrecta | 34 |
| Ambigua | 19 |
| Total único revisado | 287 |

La precisión presentada es **81,53%** (234/287), con intervalo de Wilson del 95% de 76,64% a 85,60%. Incluso si las 19 ambiguas resultaran correctas, sería **88,15%**. No se cumple el umbral de promoción.

El campo `complete:false` guardado compara la revisión con los 300 registros, incluidos los duplicados. No implica que falten valoraciones únicas: el recálculo y la comprobación de certificación reconocen la revisión completa. El 78% del contador de todos los registros utiliza ese denominador de 300 y no es la precisión sobre preguntas únicas.

## Errores objetivos marcados como correctos

| ID | Solicitud | Respuesta del modelo | Problema |
| --- | --- | --- | --- |
| 7 | `params=12e9` | `1200000000` | Debe ser `12000000000`. |
| 107 | `params=24e9` | `24000000` | Debe ser `24000000000`. |
| 207 | `params=48e9` | `48000000` | Debe ser `48000000000`. |
| 113 | Ordenar `['aaa','b','cc']` por longitud | `['b','ccc','aaa']` | Cambia un elemento: `cc` pasa a `ccc`. |

Estos cuatro casos requieren reconsiderar la valoración. Se conservan las decisiones originales; el porcentaje presentado no se ha recalculado sustituyéndolas.

## Casos semánticos que requieren reconsideración

- **18:** define alucinación como percepción mental, sin explicar la generación de información infundada en un LLM.
- **44:** la explicación del sesgo de anotación no identifica adecuadamente la influencia de los anotadores.
- **59:** describe evaluación ciega como decidir con información confusa o falsa; debe explicar qué información se oculta al evaluador para reducir sesgos.
- **89:** describe evaluación adversarial como comparar opciones, sin explicar entradas o ataques diseñados para provocar fallos.
- **118:** ofrece un ejemplo de respuesta inventada en lugar de definirla.
- **179, 249:** conviene aclarar si se pide evaluación humana en paralelo o procesamiento informático; la respuesta trata de CPU e hilos.
- **254:** revisar si explica que un paso depende de los resultados de los anteriores.

Son observaciones para revisión, no cambios automáticos de etiqueta.

## Criterios que deben aclararse

Revisar los IDs **5, 13, 26, 71, 132, 137, 202, 226, 237 y 242**. Hay empates de longitud sin regla de desempate, ordenaciones sin dirección indicada y frases abiertas con más de una palabra coherente. Por ejemplo, en el ID 5 `moe` y `mlp` tienen la misma longitud; sin exigir orden estable, ambas posiciones son admisibles. En los IDs 132 y 137, palabras como «completo» y «completa» pueden satisfacer la frase aunque difieran de la referencia.

Para valorar estos casos, aceptar equivalencia semántica cuando corresponda; exigir valores y tipos exactos en JSON y conservar todos los elementos al ordenar. Si la solicitud no define un criterio necesario, dejar constancia de la ambigüedad. No excluir casos ni cambiar criterios solo para elevar la puntuación.

## Certificación y siguiente paso

La comprobación reconoce **287/287 valoraciones únicas completas**, pero mantiene pendiente la precisión humana superior al 90%, el desarrollo original superior al 90% y las instrucciones congeladas superiores al 90%. No se ha promocionado el modelo.

Reconsiderar primero los casos señalados, guardar una nueva exportación y conservar esta como evidencia histórica. Las correcciones del modelo deben entrenarse con ejemplos de desarrollo separados; este test no debe convertirse en material de entrenamiento. Para medir una nueva generalización hará falta otro test independiente congelado.

La declaración de autoría humana se conserva como declaración del usuario; esta auditoría no demuestra por sí sola independencia respecto al entrenamiento.

## Trazabilidad

- Exportación SHA256: `b367d0213bc8fdd7784788929770326177f0e242a588713f3e91c5006a0086ef`.
- GGUF SHA256: `73418f3df9e93dee05362cd762efafb67a6c59306a533692508a2ec38c7a76b4`.
- Dataset SHA256: `8426e4d949f866f328233a66188ffe04ac9f5db61468d90f785f0e4b6f4bc0bd`.
- Evidencia: `docs/evidence/human-review-v7-audit-2026-10-01.json`.
- Comprobación: `docs/evidence/instruction-v7-certification-r1/instruction-v7-certification-gates.json`.

El archivo original, las preguntas y las valoraciones no se han modificado.
