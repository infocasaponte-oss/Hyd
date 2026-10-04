<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4i-2: despacho e worker compartidos

`hydra/core/outbox_worker.py` pasa a ser a implementación única do worker,
con alias do módulo antigo. Conserva backoff, contador de intentos, dead letters,
publicación e bucle asíncrono. O seu contrato estrutural `MessageDispatcher`
acepta ambos adaptadores sen depender de corpus nin de runtime.

`hydra/core/outbox_dispatch.py` centraliza a selección exacta de topics.
Os adaptadores conservan os efectos e esquemas actuais:

| Adaptador | Topic | Efecto |
| --- | --- | --- |
| OutboxDispatcher | event | Evento durable con source_message_id para deduplicación |
| OutboxDispatcher | provenance | Acción encadeada con source_message_id |
| OutboxDispatcher | corpus | CorpusRecord do runtime e append_once |
| CaptureDispatcher | capture.ledger | Evento no ledger da plataforma |
| CaptureDispatcher | capture.corpus | CorpusRecord da plataforma e ingest |

Consérvanse os textos de erro dos topics descoñecidos e dos destinos ausentes.
Non se mesturan colas, permisos nin formatos de corpus. A entrega continúa
sendo polo menos unha vez; este refactor non introduce unha garantía nova de
exactamente unha vez no ledger de captura.

Caracterización inicial: 16 probas aprobadas e 4 omitidas por PostgreSQL local
non configurado. A CI executa a integración PostgreSQL. As probas adicionais
comproban identidade do worker, os erros exactos, intentos e dead letters.

## Pendentes

O adaptador OutboxDispatcher permanece en runtime ata unificar os contratos
de corpus e as súas regras de dereitos/privacidade en F4g. Artefactos e crenzas
seguen pendentes en F4i. Non se modifican endpoints nin se promove un modelo.
