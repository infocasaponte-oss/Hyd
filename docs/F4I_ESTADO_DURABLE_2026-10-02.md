<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4i-1: estado durable e readiness

Este paso traslada implementacións sen cambiar esquemas, nomes de streams,
ficheiros, SQL, hashes nin condicións de saúde.

| Orixe en runtime | Destino | Función |
| --- | --- | --- |
| hash_chain | core.hash_chain | Hash canónico e rexistro compartido de locks |
| events | core.durable_events | Envelope v2, cadea JSONL, idempotencia e integridade |
| provenance | provenance.ledger | Cadea de accións e ancoraxe do seu hash |
| outbox | core.outbox | Transacción SQLite, reintentos e dead letters |
| outbox_metrics | core.outbox_metrics | Resumo sen reclamar mensaxes en PostgreSQL |
| readiness | deploy.readiness | Saúde LLM, worker, cadeas e límites de backlog |

`core.events` continúa definindo os eventos da plataforma; non é o mesmo
contrato que o envelope durable. `provenance.engine` segue construíndo fontes
de claims; o ledger conserva o rexistro de accións. Ningún se sobrescribe.

A captura da plataforma xa compartía a clase de outbox. Agora importa a súa
implementación canónica, igual que o backend PostgreSQL. Os aliases antigos
comparten a instancia de módulo e os locks. Consérvase a ancoraxe no ledger
asinado e as condicións actuais de `/ready`.

Antes do traslado pasaron 18 probas de caracterización. Despois execútanse
tamén worker, dispatcher, administración, captura, ancoraxe e integridade,
as probas novas de aliases e reapertura/idempotencia, os contratos F0 e CI.

## Pendentes

O despachador aínda depende de `runtime.corpus`; o worker úsao como contrato.
A integración dos topics de captura e runtime require caracterizar primeiro
os seus efectos e a deduplicación do corpus. Artefactos e crenzas tamén seguen
pendentes en F4i. Este paso non declara completada toda a unificación de F4i
nin certifica modelos, nin modifica o gateway activo ou CeltIA.
