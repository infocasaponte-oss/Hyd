<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4j-2: contratos da fábrica e rexistro de despregamentos

Base: integration/hydra-1.0 despois da PR #65.

BuildState, ModelLineage, ModelVariant, file_sha256 e lineage_hash pasan de
runtime/model_factory a model_factory/contracts. O ledger histórico permanece
no runtime porque usa runtime_path; non se retira nin se cambia a súa persistencia.

Deployment, DeploymentState, DeploymentRegistry e DeploymentResolver pasan a
hydra/deploy. Os imports antigos reexportan as mesmas clases. Os consumidores
de produción pasan aos módulos canónicos, incluída a ponte entre fábrica e motor.

Conserváronse os campos e valores dos contratos, as transicións permitidas,
a activación por capacidade e o rollback. Engadíronse tests de identidade de
tipos e roundtrip dun JSON de variante fixo. F0 verifica HTTP/CLI sen rexenerar
os snapshots. Os tests existentes de promoción e stores caracterizan o resto.

Este paso desbloquea parte de F4j e o subgrupo de identidade/linaxe de F4h.
Non completa ningunha das dúas fases: quedan stores, controlador, saúde,
tráfico, readiness, validación e os demais compoñentes da fábrica.

Non se modifica o gateway vivo, non se rotan claves e non se migra almacenamento.
