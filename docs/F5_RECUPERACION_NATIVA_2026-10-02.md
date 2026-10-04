<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: arranque e recuperación compartidos

bootstrap_runtime pasa a hydra.core.native_bootstrap e recover_pending a hydra.core.outbox_recovery. A API usa directamente o arranque canónico. Os módulos antigos manteñen a identidade mediante aliases.

Non cambian os límites de lote, o máximo de lotes, os contadores nin a condición de saída: se un lote non publica mensaxes, o arranque remata aínda que haxa reintentos ou dead letters. O worker periódico segue sendo quen xestiona traballo posterior.

As probas conservan a recuperación de mensaxes persistidas en SQLite e caracterizan os reintentos, os contadores e o límite máximo. As probas PostgreSQL requiren HYDRA_IT_POSTGRES ou a CI de integración.

Non se baleiran colas reais nin se reinician servizos. A fachada aínda depende da vista de configuración do runtime; a converxencia dos kernels e o traslado final da API seguen pendentes.
