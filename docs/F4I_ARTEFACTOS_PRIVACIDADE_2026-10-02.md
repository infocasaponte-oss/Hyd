<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4i-3: artefactos por tarefa e scanner

`runtime.artifacts` pasa a `artifacts.task_store`, conservando ArtifactRecord,
put_bytes/put_text, get_bytes/get_text, digest_of, os manifestos locais e o stream
`runtime/artifacts.jsonl`. O nome distingue o adaptador de tarefas do almacén
de plataforma, que conserva o seu envelope ArtifactManifest e API pública.

`runtime.privacy` pasa a `corpus.artifact_privacy`. Conserva os límites de
lectura, os estados do escaneo, a detección compartida con PrivacyGate e os
contadores. Os contratos continúan en `corpus.privacy_contracts`.

Os módulos antigos son aliases das mesmas instancias; os consumidores de
produción usan os imports canónicos. Os dous almacéns xa compartían os blobs
en modo compartido: este paso non cambia esa arquitectura nin migra ficheiros
automaticamente. A adopción ao ler blobs locais segue comprobando o seu hash.

## Validación

14 probas de caracterización pasaron antes do movemento. Probas adicionais
comproban adopción dun blob local ao almacén da plataforma sen cambiar o
manifesto, serialización dos rexistros compartidos, límite de lectura e
rexeitamento de UTF-8 inválido polo scanner. Executar ademais os backends,
captura, replay, privacidade, contratos F0, copyright, Ruff e CI.

## Pendentes

A unificación do envelope de manifestos require un adaptador explícito para
conservar ambos contratos e os datos existentes. Crenzas, calidade, captura e
dataset_factory seguen pendentes no plan. Non se cambia o gateway activo,
non se modifica CeltIA e non se certifican pesos.
