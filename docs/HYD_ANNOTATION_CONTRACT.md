<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Anotacións humanas auxiliares · hyd-human-annotation/1

As dez rutas e a súa definición actual non cambian nesta entrega. Cada fila
fonte pode incluír `annotations`, unha lista de eventos; o builder valida e
conserva todos, sen substituír pregunta, etiqueta, dereitos ou historial.
Non escolle unha revisión como verdade nin resolve desacordos automaticamente.

Cada evento require exactamente estes campos:

| Campo | Significado |
|---|---|
| format | `hyd-human-annotation/1` |
| event_id | Identificador de evento, único dentro do rexistro |
| record_sha256 | SHA256 do texto orixinal UTF-8, sen recortar/normalizar |
| reviewer_id | Identificador pseudónimo da persoa declarada; non un correo |
| reviewer_kind | `human`; opinións AI deben conservarse noutro campo/contrato |
| created_at | ISO 8601 con timezone |
| status | `pending` ou `reviewed` |
| risk_kind | `unknown`, `benign`, `dangerous`, `security`, `privacy`, `high_risk` |
| context_status | `unknown`, `sufficient`, `missing` |
| abstain_reason | `unknown`, `none`, `dangerous`, `missing_context` |

Un evento pending só admite unknown nos tres eixos. Non implica benign,
sufficient nin none. Un evento reviewed require polo menos un eixo explícito;
os outros poden quedar unknown e non deben contarse como negativos.
Dangerous abstention require risk_kind=dangerous; missing_context require
context_status=missing. Baixa confianza do modelo non é un motivo humano e
non se admite neste contrato.

O esquema valida declaracións, non autentica a persoa: escribir human non
demostra revisión humana real. A API/BD deberá ligalo á sesión, permisos de
propietario e identidade confirmada. Dúas contas non se transforman en dúas
persoas. Esta entrega non crea permisos administrativos nin migra Lovable.

## Uso e límites

O campo é opcional para compatibilidade co corpus histórico. Non se fabrican
anotacións cando está ausente. As anotacións non conceden consentimento nin
dereitos e non son targets de adestramento nesta entrega. O builder conserva
o historial por valor; a implementación da persistencia deberá ser aditiva.

A ausencia de marca non é un negativo. Para avaliar falsas alarmas serán
necesarios casos negativos revisados e denominadores por subtipo. A próxima
entrega debe resolver selección/adjudicación de eventos e particións por
persoa/familia antes de usar estes datos para medir ou adestrar E3.

Probas: hash con espazos/saltos, pendente fronte a negativo, timestamp,
revisión AI rexeitada, inconsistencias entre eixos, eventos duplicados e
round-trip das preguntas, etiquetas, dereitos e historial.
