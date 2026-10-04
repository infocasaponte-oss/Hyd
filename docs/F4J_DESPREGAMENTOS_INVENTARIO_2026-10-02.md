<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4j: inventario e primeira migración

Data: 2 de outubro de 2026. Base: integration/hydra-1.0, dc790343.

## Inventario antes da migración

| Módulo runtime | Función principal | Dependencias pendentes |
|---|---|---|
| deployment | Deployment, DeploymentState | ModelVariant da fábrica |
| deployment_controller | fases, rollback, EvidenceRejected | rexistro, stores e evidencias de tráfico |
| deployment_evidence | políticas, ShadowEvidence, CanaryEvidence, shadow_passes, canary_passes | ningunha do runtime |
| deployment_evidence_store | persistencia das evidencias de promoción | runtime_path |
| deployment_registry | selección e rexistro de despregamentos | Deployment |
| deployment_resolver | resolución por capacidade | Deployment e rexistro |
| deployment_store | persistencia, restauración e validación | ModelVariant, validador, runtime_path |
| deployment_validation | comprobación do artefacto | model_scout e ModelVariant |
| traffic_router | selección de tráfico activo/canary/shadow | rexistro e saúde |
| runtime_health | estado de saúde e circuíto | almacén de saúde |
| runtime_health_store | persistencia dos circuítos | runtime_path |
| runtime_evidence | medición de tráfico e agregados shadow/canary | runtime_path |
| health_gate | espera asíncrona de HTTP 2xx | ningunha do runtime |
| readiness | estado ready do nodo | eventos, outbox, métricas e procedencia |

## F4j-1 realizado

deployment_evidence e health_gate pasan a hydra/deploy. Os consumidores de
produción usan as rutas novas. As rutas hydra/runtime quedan como compatibilidade.
Non cambian limiares, métodos de promoción, serialización, URLs nin almacenamento.

O módulo antigo de health_gate conserva a identidade do novo módulo para que
os consumidores que substitúen o reloxo ou HTTP nos tests sigan funcionando.
As clases de evidencias conservan identidade entre ambas rutas.

Antes de mover: 27 tests de despregamento, tráfico, saúde, readiness e contratos
pasaron. Engadíronse tests explícitos de identidade das clases, esquemas e módulo.
Os tests existentes de promoción, API admin e saúde caracterizan o comportamento.
Os snapshots HTTP/CLI non se rexeneran: deben permanecer iguais.

## Seguinte subgrupo

Mover o resto require primeiro situar os contratos de fábrica, runtime_path e
os almacéns compartidos nos paquetes canónicos. Non se permiten novas importacións
plataforma → runtime para facer unha migración aparente. Conservar os adaptadores
ata F6b e comprobar F0 e os tests de rollback en cada subgrupo.

Esta PR non completa F4j, non retira hydra/runtime e non modifica o gateway vivo.
