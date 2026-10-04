# Corpus de decisiones HYDRA v3

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

El corpus generado en `data/decision-corpus-v3` contiene 2.800 filas:

- `train.jsonl`: 1.600 filas, único split con `training_allowed=true`.
- `calibration.jsonl`: 200 filas, reservado para temperatura/umbral.
- `test.jsonl`: 1.000 filas, congelado para la comparación final.

Hay diez familias: chat, coding, reasoning, research, vision, tool_use, security,
privacy, abstain y high_risk_review. La construcción es determinista, deduplica
por prompt normalizado y escribe un hash por fila y por archivo. El manifiesto fija
los conteos y el hash del corpus.

La mayoría de las variaciones son plantillas HYDRA con sufijos deterministas; eso
permite probar el flujo de admisión y las particiones, pero no equivale a variedad
humana ni a una evaluación de calidad. Antes de entrenar se debe revisar una
muestra, añadir paráfrasis humanas y conservar el test fuera del ciclo de ajuste.

Manifiesto: [manifest.json](../data/decision-corpus-v3/manifest.json).
