<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Contraste da auditoría — 2026-10-03

O informe externo identifica riscos útiles, pero algunhas conclusións requiren
matices verificables no código:

- `human-dev-v2.jsonl` contén 1.000 filas e só 200 textos únicos. O xerador
  `human_dev_v2.py` usa catro patróns e cinco temas por etiqueta, repetidos.
  Non acredita 1.000 exemplos humanos independentes nin revisión individual.
  `boundary_family` é a etiqueta: dividir por ese campo exclúe clases enteiras.
  Calquera nova versión necesita familias de expresión distintas, dereitos e
  revisión acreditados, calibración separada e un test independente novo.
- O Hyd baseline mantivo os mesmos pesos e limiares tras o diagnóstico das
  100 paráfrases. O seu peso SHA é
  `0616432c984c4240e0459a3a4e063d268267a3bcf9a94061e22a458d376629ce`.
  O test está marcado como diagnóstico non independente; non se usou para
  elixir novos pesos. A independencia global dese benchmark está comprometida
  polas promocións e modificacións previas, polo que non habilita autoridade.
- Un porto pechado non demostra ausencia de dependencia de Kev: o Studio
  candidato e as opcións de bootstrap aínda ofrecían ese camiño. Esta primeira
  integración cambia o Studio a Hyd local, con artefactos empaquetados e sen
  autoridade, preservando as interfaces históricas optativas para a retirada
  posterior. Non afirma aínda a eliminación de todos os clientes ou scripts.
- `models/hydra-decision-v4/promotion.json` referencia un calibrador de Kev,
  un módulo de política xa retirado e o test de regresión reutilizado. Esa
  promoción histórica non é evidencia válida para habilitar autoridade nova.
  A integración de Hyd non carga esa promoción nin os pesos v4.

O candidato novo non adestra co test nin promove un modelo por estas cifras.
A mellora da concorrencia CPU é limitada a catro traballadores; o encoder
contextual conserva un slot para manter illamento e memoria acoutada.
