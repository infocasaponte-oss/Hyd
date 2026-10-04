<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4j-3: evidencias, saúde, tráfico e controlador

Base: integration despois das PRs #64 e #66.

Seis implementacións pasan a hydra/deploy: deployment_evidence_store,
runtime_health_store, runtime_health, runtime_evidence, deployment_controller
e traffic_router. As rutas antigas apuntan aos mesmos módulos, para conservar
tamén os globals utilizados polos consumidores e polos tests.

A lectura temperá de variables e .env pasa a core/environment; a resolución de
HYDRA_RUNTIME_DIR pasa a core/runtime_paths. Mantense a precedencia proceso →
.env → valor por defecto e a resolución das rutas ao importar os módulos.
Os módulos antigos seguen reexportando os símbolos existentes.

Non cambian os esquemas SQLite, nomes de streams PostgreSQL, rexistros de
evidencias, cálculo de percentís, limiares de promoción, circuítos nin rollback.
Non se executan migracións de datos nin se reinicia o gateway vivo.

Tests: stores de saúde e evidencias, agregación de tráfico, controlador e API
admin; identidade dos módulos e precedencia de configuración; contratos F0.

F4j continúa pendente: deployment_store, deployment_validation e readiness.
O validador depende do inventario e lector GGUF, que requiren o seu inventario
e caracterización dentro de F4h. Readiness depende de outbox e procedencia.
