<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: stores nativos compartidos

A implementación de pg_stores pasa a hydra.core.native_stores. A API usa directamente a factoría canónica; o import antigo conserva a identidade do módulo para os consumidores e os parches.

Non cambian SCHEMA, táboas, payloads, captura terminal, claim de outbox, importación de SQLite, límites de spans nin estado dos circuitos por nodo. Non se executa unha migración nin se alteran servizos activos.

A caracterización existente de backends segue sendo a validación funcional. Localmente PostgreSQL require HYDRA_IT_POSTGRES; a CI de integración configura PostgreSQL e Redis e executa test_runtime_db_backends e test_documents_backends.

Este paso centraliza a persistencia da execución nativa; segue pendente o adaptador común dos dous contratos de kernel e a retirada gradual das fachadas.
