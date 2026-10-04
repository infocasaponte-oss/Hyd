# Continuación de auditoría semántica y comparación remota — 2026-09-30

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Alcance comprobado

Refs actualizadas con `git fetch origin`. Comparación completa de genealogía de las ocho ramas remotas (28 pares), commits exclusivos y archivos diferentes respecto de main. Las diferencias de árboles incluyen cambios históricos ya incorporados a main: no deben confundirse con propuestas nuevas. No se han fusionado ramas, modificado servicios ni alterado corpus o pesos.

| Rama | Commits solo main | Commits solo rama | Archivos diferentes |
|---|---:|---:|---:|
| origin/codex/finish-hydra-gguf | 524 | 0 | 406 |
| origin/dependabot/pip/huggingface-hub-0.36.2 | 70 | 1 | 131 |
| origin/dependabot/pip/protobuf-7.36.2 | 70 | 1 | 131 |
| origin/dependabot/pip/transformers-5.17.0 | 59 | 1 | 128 |
| origin/feat/hydra-vision-qwen3-vl | 0 | 1 | 4 |
| origin/fix/ollama-primary-model-api | 47 | 0 | 125 |
| origin/integration/hydra-1.0 | 3 | 0 | 10 |
| origin/main | 0 | 0 | 0 |

## Decisiones recomendadas

- Usar main como base: integration/hydra-1.0 es antecesora y carece de los tres commits recientes, incluyendo la protección del resultado ante agotamiento del presupuesto y el filtrado de modelos ausentes.
- feat/hydra-vision-qwen3-vl aporta un commit nuevo en cuatro archivos: sustituye gemma4:26b por qwen3-vl:8b y mueve think al nivel superior de la petición Ollama. Revisado el diff completo. El test añadido comprueba la petición con transporte simulado; no acredita visión real, VRAM ni latencia. reasoning posterior puede sobrescribir think. Integrar solo con validación física y de precedencia.
- Las ramas codex/finish-hydra-gguf y fix/ollama-primary-model-api no tienen commits exclusivos. No restaurar sus árboles antiguos sobre main.
- Las tres ramas Dependabot tienen un commit exclusivo de cambio de versión cada una. Revisados los diffs desde merge-base. No actualizar transformers de 4 a 5 sin probar entrenamiento, PEFT, tokenizer, merge y conversión GGUF en entorno aislado. La comparación no certifica compatibilidad de ninguna actualización.

## Hallazgos nuevos confirmados

1. **P1 — ruta de publicación sin confinamiento.** hydra/corpus/factory.py:46,324-335 acepta name/version y nombres de split sin restricciones, los concatena con la carpeta de releases. platform_routes.py:457-461 expone la construcción con autenticación. `../outside` pasa validación y resuelve fuera de la raíz. La prueba solo calculó la ruta, sin escribir fuera. Validar identificadores y resolver todas las rutas bajo la raíz. No es un acceso anónimo remoto: aplica la política de auth de main.py.
2. **P1 — release mutable.** factory.py:326 usa exist_ok=True y sobrescribe tablas y manifest. Repetir nombre/version rompe la garantía documental de congelación y trazabilidad. Usar publicación atómica, identidad ligada al hash y rechazo de contenido distinto para una versión existente.
3. **P1 — separación insuficiente.** factory.py:308 divide por hash de ID; no agrupa familia de paráfrasis. IDs distintos de un mismo problema pueden cruzar train/test. Separar por familia y origen antes de generar variantes.
4. **P2 — porcentajes inválidos.** DatasetSpec acepta splits todos cero; split produce ZeroDivisionError con entradas ordinarias. Debe rechazar valores no finitos, negativos, total cero y claves inseguras antes de construir.
5. **P2 — cobertura silenciosa.** _quota:278 excluye del cálculo los grupos solicitados vacíos, por lo que no bloquea la ausencia de una lengua/dificultad requerida. Emitir déficit y rechazar cobertura obligatoria incumplida.
6. **P2 — colisión de UI.** studio.html:50,89 repite cq. chatSend:189 y corpusSearch:203 leen el mismo primer elemento. El buscador puede usar el mensaje del chat en lugar de su entrada. Separar IDs y verificar ambos flujos.
7. **P2 — logs sin límite durante ejecución.** model_factory/runner.py:40 captura stdout/stderr completos con communicate; el recorte ocurre después. Entrenamientos largos pueden agotar RAM. Leer por bloques, persistir logs y limitar el buffer.
8. **P2 — ciclo de vida de procesos incompleto.** runner.py:41-45 mata el proceso directo al vencer timeout; no garantiza detener descendientes y no maneja cancelación. Requiere supervisor por árbol/Job Object en Windows y prueba de cancelación.

## Evidencia y límites

- Inventario anterior: 616 archivos versionados, hashes y sintaxis Python; 483 pruebas pasadas y 5 omitidas. Esa suite se ejecutó sobre el checkout integration; no certifica main ni la rama visual.
- Nuevas sondas reproducibles: IDs HTML duplicados, ruta escapada sin escritura y particiones cero. Evidencia en semantic-probes-2026-09-30.json.
- remote-branches-2026-09-30.json conserva SHA, merge-base, commits exclusivos y diferencias completas; branch-pairs-2026-09-30.json conserva los 28 pares.
- Revisión semántica profundizada en fábrica de datasets, ejecución de comandos, autenticación, rutas de construcción, workspace y diff visual/resiliencia. No se declara revisión línea a línea del 100% de archivos.
- Pendiente: revisión profunda de todos los restantes módulos de runtime, persistencia, promoción, privacidad/licencias, concurrencia y recuperación; resolver dependencias en entorno aislado; verificar entrenamiento e inferencia sostenida en GPU.

## Orden de resolución

P0: integridad de releases y rutas; separación independiente de datos y retirar la promoción basada en test contaminado. P1: calibración realmente aplicada y contrato único de promoción; supervisor de jobs. P2: UI y cuotas. Después, main + candidata visual, pruebas físicas, benchmark del GGUF y despliegue gradual con rollback.
