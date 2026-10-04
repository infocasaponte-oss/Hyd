<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# A03: particións por persoa e familia

Uso: `python -m hyd_calibrator build --corpus SOURCE.jsonl --out NEW_SNAPSHOT --grouped`.
O modo require `meta.person_id` e `meta.family_id` explícitos en cada rexistro.
Son códigos opacos declarados; non introducir correos nin inferir persoas de
contas, estilos de escritura ou opinións de IA. As contas da mesma persoa deben
compartir person_id. Un family_id identifica unha familia revisada de preguntas
relacionadas, incluíndo paráfrases; non representa simplemente unha clase.

O algoritmo calcula compoñentes conectados: mesma persoa, mesma familia ou texto
normalizado igual enlazan rexistros de maneira transitiva. Cada compoñente vai
enteiro a train/calibration/test por hash determinista, con proporcións nominais
70/15/15. Non garante proporcións exactas nin presenza de todas as clases en cada
partición: consultar o manifest e non certificar un test sen cobertura axeitada.
Se non aparecen as tres particións rexeita antes de crear o snapshot. Un corpus
dunha soa persoa non serve para estas tres particións independentes.

O hash é reproducible para o mesmo corpus e independente da orde. Ao incorporar
novos rexistros poden fusionarse compoñentes e cambiar a asignación: conservar
snapshots inmutables e non comparar como se fose o mesmo test. Os group_id,
hashes de ficheiro, política e número de grupos quedan no manifest/dataset.
`independence_verified=false` conserva a distinción entre declaración e proba.

O modo histórico sen --grouped continúa dispoñible para diagnósticos comparables;
non acredita independencia por persoa ou familia. Non se inventaron estes campos
para o corpus existente nin se mediu unha nova accuracy. As fixtures das probas
son datos artificiais exclusivamente para comprobar o software, nunca corpus.

Pendente: recoller/revisar declaracións reais na app, con historial exportable,
validar cobertura por clase e conxelar unha avaliación independente. A seguinte
entrega debe endurecer a admisión e reproducibilidade do especialista E2.
