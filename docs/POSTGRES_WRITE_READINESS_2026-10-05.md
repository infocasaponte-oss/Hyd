<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# PostgreSQL: lectura e escritura son comprobacións distintas

A conexión de lectura foi verificada previamente. Non se aplicou unha migración nin se comprobou escritura. A aprendizaxe e a revisión seguen co almacenamento local exportable.

O inventario real repetido o 5 de outubro confirmou que `tasks`, `events`, `memories`, `inference_runs` e `model_metrics` non están en `public`. A conexión TLS funcionou; non se consultou contido das táboas nin se executou SQL de escritura. Esta evidencia confirma que a migración básica segue pendente.

A revisión do código confirma que `create_pool` executa automaticamente `sql/schema.sql` no bootstrap. Ese SQL inclúe máis ca memoria: tarefas, eventos, telemetría, colas e libro de procedencia, con modificacións de columnas e triggers. Non se debe activar ese bootstrap no proxecto Supabase compartido como se fose unha simple proba de conexión.

O probe de lectura agora informa tamén do inventario de táboas e das cinco táboas básicas ausentes en `public`. Todas as consultas execútanse nunha transacción de lectura, con TLS; non le contido das preguntas. A presenza de nomes non confirma tipos de columnas, permisos nin illamento, polo que `write_readiness_verified` segue sendo falso.

Antes de activar escritura:

1. Comparar táboas, columnas e permisos reais co SQL versionado; comprobar posibles colisións coa aplicación existente.
2. Preparar unha migración específica para os compoñentes necesarios, cun esquema e rol propios, sen aplicar o bootstrap completo ao proxecto compartido.
3. Probar a migración nunha base de ensaio: escritura, lectura tras reinicio, illamento entre persoas, exportación e recuperación.
4. Gardar hash e resultado da migración aplicada; activar só os backends verificados. Non publicar credenciais nin corpus en Git.

Esta revisión prepara a comprobación. Non afirma que o esquema remoto exista nin que a escritura estea habilitada.
