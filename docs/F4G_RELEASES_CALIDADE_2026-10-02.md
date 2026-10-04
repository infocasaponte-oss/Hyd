<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4g-2: releases de artefactos e calidade de parches

A fábrica canónica incorpora `release_artifacts(name, records, root=...)`.
Delega no adaptador `corpus.artifact_datasets`, que conserva DatasetManifest,
o hash, o nome do ficheiro e as prohibicións de rexistros non CURATED e hashes
duplicados. Non exporta texto de adestramento nin elimina os controis de
dereitos, contaminación e calidade da fábrica de texto.

`runtime.dataset_factory` e `runtime.corpus_quality` son aliases dos módulos
canónicos `corpus.artifact_datasets` e `corpus.patch_quality`. A captura usa
a regra canónica de calidade: SILVER só se existen os cinco tipos de evidencia
e o verification-report declara verified=True; en caso contrario BRONZE.

Antes dos cambios pasaron 19 probas de caracterización. A validación engade
o acceso desde a fábrica canónica, persistencia co esquema antigo e ausencia
de manifestos para corentena, bloqueados, tombstones e duplicados.

## Pendentes

LearningCapture segue dependendo do contrato de crenzas do runtime. Integrar
esa captura require conservar EvidenceRef, BeliefStatus e os datos anteriores
ao adaptador do World Model. A fábrica de artefactos só conxela manifestos:
non certifica que o seu contido sexa un dataset completo de texto nin promove
modelos. Tampouco cambia CeltIA ou o servizo activo.
