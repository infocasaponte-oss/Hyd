# Mejoras implementadas del plan Kev

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Commit de esta iteración: opciones canónicas y calibración externa.

`LocalSystemOneProvider` conserva el orden que solicita el llamador para validar
el contrato, pero transmite las opciones de elección ordenadas por etiqueta. Al
recibir la distribución, la reconstruye en el orden original. Se cubren opciones
desordenadas, validación y empate; score/noul conservan su semántica ordinal.

`TemperatureCalibrator` aplica una transformación reproducible fuera del modelo.
`fit_temperature` prueba una lista cerrada de temperaturas y minimiza NLL solo en
filas con etiqueta de calibración. El manifiesto incluye formato, versión,
temperatura y hash del dataset; un archivo sin hash no se carga. El observador
puede usarlo para calcular probabilidades calibradas, pero sigue sin autorizar
herramientas.

Validación local: 17 pruebas del proveedor, observador y calibrador pasan; Ruff y
`git diff --check` correctos. El resultado de Kev real aún no se ha recalibrado:
eso requiere generar y congelar el corpus v3 de 200/1.000 casos indicado en el
plan. No se debe llamar a este cambio una mejora de accuracy hasta medir ese test.
