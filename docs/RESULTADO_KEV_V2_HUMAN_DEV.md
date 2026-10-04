# Kev v2 después de incorporar desarrollo humano

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Se creó `human-dev-v1.jsonl` con 100 ejemplos humanos, diez por familia. Tiene
frases distintas del test congelado `human-paraphrase-v1.jsonl`, permiso explícito
de entrenamiento y hashes por fila.

La cabeza v2 se reentrenó con `decision-corpus-v3/train.jsonl` más este desarrollo
humano. Se volvió a medir exclusivamente contra las 100 paráfrasis congeladas:

| Modelo | Accuracy | Límite Wilson 95 % | ECE | Brier |
|---|---:|---:|---:|---:|
| v2 sintético | 59 % | 49,2 % | 0,1809 | 0,6153 |
| v2 + desarrollo humano | **70 %** | 60,4 % | 0,2634 | 0,5107 |

La mejora de accuracy es real sobre este test congelado, pero la calibración
empeora y el límite estadístico sigue siendo insuficiente. El modelo queda como
`candidate-development`, fuera del router productivo. La compuerta HYDRA sigue
siendo obligatoria para seguridad, privacidad, abstención y alto riesgo.

Próximo ciclo: aumentar el desarrollo humano por clase, revisar desacuerdos entre
anotadores, aplicar calibración con el split separado y añadir casos difíciles de
cambio mínimo. No se debe reutilizar este test para ajustar temperatura ni pesos.
