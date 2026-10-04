<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4g-1: regras de admisión de candidatos de artefactos

O curador da plataforma incorpora `artifact_status`, a regra de admisión que
antes pertencía ao CorpusGate do runtime. Exixe os tres permisos explícitos,
evidencia de dereitos e escaneo CLEAR. FLAGGED bloquea; NOT_SCANNED e INCOMPLETE
quedan en corentena. Consérvanse o tier declarado e o hash orixinal.

O envelope, gate, índice e almacén destes candidatos pasan a
`hydra/corpus/artifact_candidates.py`; os contratos de escaneo pasan a
`hydra/corpus/privacy_contracts.py`. O scanner segue no runtime porque depende
do almacén de artefactos, pendente de F4i. Os aliases conservan os imports.

Non se equipara CURATED dun candidato de artefactos con autorización automática
para exportar texto ao adestramento: o corpus de texto segue pasando tamén por
calidade, licenza, pseudonimización, deduplicación e contaminación no curador.

Coa dependencia de corpus resolta, OutboxDispatcher pasa a
`hydra/core/outbox_dispatcher.py`, sen cambiar topics ou efectos. O worker e
os dous adaptadores quedan fóra do runtime; os envelopes distintos consérvanse.

## Evidencia

25 probas de caracterización pasaron antes dos cambios. Un fixture con 64
combinacións de permisos, evidencia e estados de privacidade foi xerado coa
implementación orixinal do commit `3436e8a`, non coa nova regra. As probas
comparan o estado e o hash completos para cada combinación. Tamén se executan
privacidade, captura, dataset, deduplicación, outbox, F0 e CI completa.

## Pendentes

Integrar o scanner e os rexistros de artefactos; revisar dataset_factory fronte
á fábrica de corpus, preservar só CURATED e deduplicación; integrar calidade
e captura. Non se declara rematado F4g, non se cambia CeltIA nin se promove un
modelo. As regras adicionais do corpus de texto non se relaxan.
