# HYDRA v7: generación JSON y revisión humana

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Qué se ha implementado

Se añadieron 320 instrucciones sintéticas nuevas, con 224 para entrenamiento y 48 para cada partición de desarrollo y calibración. Se entrenó sobre v5 en CUDA, se fusionó el adaptador y se creó un GGUF Q5_K_M. El entrenamiento tiene 836 ejemplos y el test original de 48 instrucciones sigue idéntico. Las 300 preguntas externas no se usan para entrenar.

El intento v6 se rechazó por lectura incorrecta de UTF-8 en Windows. Se conserva con estado `REJECTED_CORPUS_ENCODING`; el registro normal de candidatos lo rechaza. V7 parte de v5, no de v6. La fábrica ahora comprueba que las filas heredadas del corpus coincidan exactamente con el padre declarado, además de verificar hashes. Hay una prueba específica contra corrupción de tildes.

El motor reconoce contratos de serialización sin exigir la palabra JSON, interpreta correctamente «sin explicación», y aplica un esquema de objeto con campos tipados sin introducir valores de referencia. Para el contrato `id/activo`, recuerda la equivalencia entre estados afirmativos/negativos y booleanos, incluida la diferencia entre habilitado y deshabilitado. No convierte a posteriori una respuesta incorrecta en la esperada.

## Resultados y alcance

| Protocolo | Resultado |
|---|---:|
| V5 sobre las mismas 188 preguntas ampliadas originales | 139/188 |
| V7 sobre las 188 preguntas ampliadas originales | 158/188 |
| V7 sobre las 140 preguntas anteriores | 138/140 |
| V7, desarrollo con contratos corregidos, generación directa | 184/188, 97,87% |
| JSON de ese desarrollo, generación directa | 76/78, 97,44% |
| JSON mediante el endpoint real del motor, sin caché | 78/78, 100% |
| Desarrollo con contratos corregidos, inferencia restringida | 186/188, 98,94% |
| Calibración original separada, generación directa | 186/188, 98,94% |
| Calibración original separada, inferencia restringida | 187/188, 99,47% |
| Test original congelado, generación directa | 24/48 |
| Test original congelado, contrato JSON tipado | 48/48 |
| Regresión de programación | 64/64 |
| Estabilidad GPU, 15 minutos | 1.383 inferencias, cero fallos y cero cambios de salida |
| Pruebas completas del repositorio | 573 aprobadas, 5 omitidas |
| Pruebas focalizadas posteriores | 44 aprobadas |

Dos redacciones sintéticas de desarrollo no especificaban correctamente las claves o sus tipos. Se conservaron sus resultados y se creó `data/hydra-instruction-v7-contract-v2`, cambiando 32 preguntas de esas dos familias, sin modificar entrenamiento, calibración, test congelado ni respuestas esperadas. El detalle antes/después está en `docs/evidence/instruction-v7-contract-corrections.json`. **El 184/188 no sustituye al 158/188 ni es un nuevo test humano independiente.** La selección y corrección del desarrollo no permiten afirmar una precisión general del 98%.

La estabilidad es un ensayo acotado: VRAM del modelo constante en 1.244.418.538 bytes, mediana 125,99 ms y p95 265,24 ms. Se probaron también llamadas del motor. No es una prueba de carga concurrente ni certifica todos los usos. Las mejoras posteriores del contrato se verifican por separado mediante el endpoint real en `instruction-v7-json-engine-live-r3.json`.

GGUF: `models/hydra-instruction-v7/HYDRA.gguf`, 1.125.049.920 bytes. SHA-256: `73418f3df9e93dee05362cd762efafb67a6c59306a533692508a2ec38c7a76b4`. Modelo de texto, sin visión. Entrenamiento: RTX 3060 Ti, 841,00 segundos, memoria máxima asignada 3.481.800.704 bytes.

## Revisión humana

Se generaron las 300 respuestas externas de v7. Hay 287 preguntas únicas y 136 coincidencias automáticas con las referencias; las coincidencias no son una valoración humana ni una precisión semántica.

La declaración del usuario «Redactadas por personas» está registrada como autoría. **No acredita que haya valorado las respuestas: siguen 0/287 valoraciones.** Las opiniones de v5 y v7 se guardan por separado y no se trasladan entre pesos.

La página muestra preguntas únicas por defecto, progreso, pendientes y el modelo revisado. Permite retomar una revisión, guardar cada valoración y exportarla. Studio incluye un enlace en Training. El evaluador de llamadas reales respeta el límite de peticiones y reintenta HTTP 429, sin desactivar la protección. Los intentos iniciales bloqueados o interrumpidos se conservan y no se usan como resultado final.

- Studio v7: http://127.0.0.1:18087/studio
- Revisar v7: http://127.0.0.1:18087/hydra/v1/evaluation/review
- Evidencias iniciales: `docs/evidence/instruction-v7-certification-r1/`
- Evidencias del contrato corregido: `docs/evidence/instruction-v7-contract-v2-*.json`

## Decisión

No se ha promocionado a producción. La generación directa del test congelado sigue en 24/48 y faltan las valoraciones humanas. El contrato del motor y el GGUF directo son dos protocolos distintos. Las mejoras de desarrollo y configuración no sustituyen esos requisitos. Para completar la parte humana, una persona debe revisar efectivamente las respuestas nuevas y guardar sus decisiones; el asistente no puede acreditar sus propias valoraciones como humanas.
