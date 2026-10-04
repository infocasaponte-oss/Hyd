<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: captura terminal compartida

A implementación de CaptureUnitOfWork e TaskCommit pasa a hydra/core/task_commit.py. O kernel nativo e os stores PostgreSQL importan o contrato canónico. hydra.runtime.capture_uow conserva unha alias do mesmo módulo durante a transición.

Non cambian a táboa task_commits, os payloads, os topics event/provenance/corpus nin os límites da transacción. Non se executa ningunha migración de datos nin se modifican os servizos activos.

A caracterización inclúe fallo inxectado en cada enqueue: ao reabrir SQLite non existe resultado terminal nin mensaxes parciais. Tamén se conserva a identidade do módulo legado para os consumidores e os parches dos tests.

Este paso elimina unha dependencia do runtime na captura compartida; non conecta aínda a fachada HTTP ao kernel da plataforma nin completa F5. Segue pendente a integración dos kernels con conservación dos contratos públicos e da persistencia PostgreSQL.
