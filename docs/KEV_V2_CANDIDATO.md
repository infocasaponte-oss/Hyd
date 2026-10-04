# Kev v2 — cabeza de decisión HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Se ha entrenado un candidato local ligero en
`models/hydra-decision-v2/classifier.json` con la implementación nativa de
HYDRA (`TextClassifier`), usando solo `train.jsonl` del corpus v3. Incluye las
diez salidas del contrato: tareas normales, seguridad, privacidad, abstención y
alto riesgo.

En el corpus sintético actual obtuvo 100 % en calibración y test, ECE 0,022 y
Brier 0,00059. Esta cifra no es evidencia de calidad general: los prompts de
test comparten plantillas y vocabulario con train. El candidato sirve para
validar el contrato y el flujo de entrenamiento; no se presenta como mejora
frente a Kev ni se promociona automáticamente.

La prueba independiente posterior con 100 paráfrasis humanas obtuvo 59 % y
demostró sobreajuste. El candidato queda rechazado para promoción; el resultado
completo está en `RESULTADO_KEV_V2_HUMANO.md`.

El manifiesto identifica la semilla, etiquetas, corpus y limitaciones. Antes de
usarlo en producción hay que sustituir o complementar las variaciones sintéticas
por paráfrasis humanas, mantener el test oculto y evaluar contra el protocolo
independiente de 1.000 casos. La compuerta determinista sigue siendo la defensa
para permisos y alto riesgo.

Pruebas: entrenamiento reproducible y presencia de las diez etiquetas verificados.
