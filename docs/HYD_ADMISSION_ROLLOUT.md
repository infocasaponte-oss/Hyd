<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Primeiro paso do plan de melloras: admisión e snapshots

Esta entrega depende da PR do calibrador independente. O entry point
`hydra.hyd.app_corpus` xa delega no builder estrito do calibrador: conserva
os metadatos/dereitos declarados, rexeita flags ausentes e non crea permisos.

Agora o loader nativo de train e calibration tamén esixe consentimento
literal `true` e dereitos declarados. Non se interpreta `"true"` ou `1` como
consentimento. A licencia nativa admitida continúa sendo
`proprietary-hydra-authored`; a validación non acredita a declaración.

Os builders e o adestrador nativo rexeitan directorios existentes. O CLI
nativo require `--out`; xa non selecciona `config/hyd` por defecto. A
promoción dun modelo segue sendo unha operación separada.

`provenance_status=source-declared` indica a natureza declarativa dos
metadatos conservados, non autoría humana verificada nin tráfico real.
Os JSONL históricos non se modifican. Se non conteñen declaracións
requiridas deben prepararse nunha nova exportación versionada, conservando
orixinais e cunha declaración explícita do propietario; nunca cubrir
campos automaticamente para conseguir que o loader acepte un lote.

## Validación

Tests de regresión: false/null/string/integer no consentimento de train e
calibration; falta de flags/permisos da fonte; intento de sobrescribir
snapshot/run. As probas anteriores do calibrador verifican preservación
de texto/metadatos/dereitos e reproducibilidade.

## Próxima entrega

A02 debe introducir un contrato auxiliar versionado para risco, contexto,
motivo de abstención e estado de revisión humana, mantendo as dez rutas.
Non cambiar o significado de etiquetas nin predicións xa almacenadas.
Non promover o modelo nin medir unha accuracy nova nesta entrega.

A admisión de avaliación diagnóstica histórica segue separada da autorización
para adestrar: o loader de informes pode ler evidencia antiga; isto non a
converte nunha fonte admitida de adestramento. O endurecemento de E2 e a
separación dev/cal/test pertencen ás entregas seguintes.
