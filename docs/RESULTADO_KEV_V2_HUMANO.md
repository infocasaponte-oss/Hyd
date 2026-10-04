# Kev v2: prueba independiente con paráfrasis humanas

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Se creó un conjunto de 100 solicitudes redactadas manualmente, 10 por cada una
de las diez familias del contrato. No comparte las plantillas del corpus v3 y
todas las filas llevan `training_allowed=false`. El conjunto es una revisión
interna de HYDRA; aún falta acuerdo entre anotadores externos.

Resultados:

- Cabeza `hydra-decision-v2`: 59/100, límite inferior Wilson 49,2 %.
- ECE: 0,1809; Brier: 0,6153; NLL: 1,4875.
- Cobertura de la cabeza: 100 %, pero con calidad insuficiente.
- Kev 0.8b original: 51/60 (85 %) en las seis etiquetas que su cabeza soporta.
- Kev original no puede evaluar `security`, `privacy`, `abstain` ni `high_risk_review`.

La diferencia entre 100 % en el corpus sintético y 59 % en paráfrasis humanas
demuestra sobreajuste a las plantillas v3. El candidato Kev v2 queda rechazado
para promoción y no entra en el router. La compuerta determinista sigue cubriendo
las cuatro clases ausentes, sin fingir que el modelo las predice.

Siguiente entrenamiento: incorporar un conjunto humano de desarrollo separado,
con paráfrasis revisadas y ejemplos difíciles, manteniendo este test congelado.
Repetir con al menos tres revisores, medir acuerdo y añadir casos de cambio mínimo
entre clases. Solo conservar una cabeza que supere el test humano, el test v3 y
los límites de calibración definidos.

Evidencia: [human-paraphrase-v1.json](evidence/human-paraphrase-v1.json).
