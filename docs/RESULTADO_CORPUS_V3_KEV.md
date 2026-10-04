# Resultado del corpus v3 contra Kev

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 30/09/2026. Se ejecutaron 1.200 inferencias reales en CUDA: 200 de
calibración y 1.000 de test, con dos solicitudes concurrentes. No hubo errores
HTTP ni respuestas malformadas.

La cobertura efectiva fue 600/1.000 en test. Kev no incluye probabilidades para
las etiquetas `security`, `privacy`, `abstain` y `high_risk_review`; esas 400 filas
quedaron fuera de las métricas de clasificación, aunque sí cuentan como una
limitación del contrato. Esto demuestra que no basta con cambiar el umbral: la
cabeza actual no cubre todas las decisiones que HYDRA necesita.

Sobre las 600 filas compatibles:

- Accuracy: 93,17 %; límite inferior Wilson al 95 %: 90,86 %.
- Brier bruto: 0,2653; ECE bruto: 0,3347.
- Temperatura ajustada solo en las 120 filas de calibración compatibles: 0,5.
- Brier calibrado: 0,1265; ECE calibrado: 0,1295; NLL: 0,3091.
- El umbral de promoción predeclarado no acepta ningún caso con la cobertura y
  precisión exigidas; la cobertura selectiva resultante es 0.

La calibración mejora mucho la distribución numérica, pero no convierte las
probabilidades en autorización. La promoción continúa bloqueada por cobertura,
etiquetas ausentes y falta de test realmente independiente para cuatro familias.

Próximo trabajo técnico:

1. Definir un contrato Kev v2 que incluya explícitamente abstención, revisión de
   alto riesgo, privacidad y seguridad, o mapearlas a una salida `review` segura.
2. Añadir ejemplos reales revisados para esas clases y recalibrar con balance por
   clase; no rellenar etiquetas ausentes con reglas sin evidencia.
3. Repetir el test completo y exigir 1.000/1.000 filas con respuesta válida,
   cobertura selectiva ≥60 % y límite inferior ≥90 %.

Evidencia: [kev-corpus-v3.json](evidence/kev-corpus-v3.json). El informe parcial
conserva las 1.200 respuestas locales; el test v3 no se incorpora al entrenamiento.
