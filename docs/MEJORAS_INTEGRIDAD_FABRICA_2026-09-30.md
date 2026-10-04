# Mejoras implementadas en fábrica y entrenamiento

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Se protege la creación de nuevos datasets: identificadores seguros, particiones finitas con peso positivo, límites de calidad y política sintética, y rechazo explícito de cobertura requerida ausente. Las versiones existentes se conservan y una segunda construcción devuelve conflicto. Los archivos se construyen en una carpeta temporal y se publican mediante rename; los fallos previos eliminan la carpeta temporal.

Las particiones agrupan componentes conectados por family_id, source_family_id, source_task_id, source_id y source_records. Si cualquier miembro pertenece al holdout temporal o adversarial, la familia completa se reserva. Esta protección necesita procedencia correcta: no puede reconocer automáticamente paráfrasis sin metadatos. La partición cambia respecto de versiones anteriores y requiere una versión nueva de dataset. Las publicaciones antiguas no se reescriben.

El entrenamiento v4 ya no regenera human-dev-v2 al arrancar. Deduplica textos normalizados, rechaza etiquetas contradictorias y registra hashes SHA256 de las fuentes. No se ha entrenado ni promocionado un candidato durante esta intervención.

El buscador del corpus tiene su propio identificador HTML. El runner drena stdout/stderr por bloques con buffers acotados; al vencer el tiempo o cancelar termina el árbol que él mismo lanzó. Las sondas de procesos crean hijos temporales propios; no detienen servicios o entrenamientos existentes. En timeout se devuelve el estado de fallo sin preservar el buffer parcial.

Pruebas nuevas: rechazo de rutas y particiones inválidas, inmutabilidad y limpieza de publicaciones fallidas, agrupación transitiva de anchors y holdout, cobertura faltante, entrenamiento sin modificación de fuentes, contradicción de etiquetas, salida abundante, cancelación y timeout con procesos reales en Windows.

Validación: suite completa con 495 pruebas pasadas y 5 omitidas (157,47 s). Las dos pruebas de integridad del entrenamiento añadidas después de iniciar esa suite también pasan; comprobación final focalizada: 11 pasadas. `git diff --check` sin errores. No se han reiniciado servicios ni realizado inferencias GPU en esta intervención.

Pendiente: calibración aplicada al router y gate independiente, procedencia completa del corpus, actualización controlada de extractores de características, validación física de visión/GGUF y recuperación transaccional de lineage/ledger después de publicar. La publicación de archivos es atómica; no constituye una transacción conjunta con el ledger. Estas mejoras no acreditan un 90% independiente ni una promoción automática.
