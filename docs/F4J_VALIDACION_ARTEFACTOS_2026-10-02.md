<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F4j-4: persistencia e validación de artefactos

O almacén e o validador de despregamentos pasan a `hydra/deploy`.
O inventario de modelos pasa a `hydra/model_factory/model_scout.py`,
e o seu lector lixeiro de metadatos a `hydra/model_factory/gguf_inspection.py`.
Este lector conserva o comportamento anterior; non substitúe o lector distinto
que xa existe en `hydra/model_factory/gguf.py`.

## Inventario e límites

| Implementación anterior | Implementación canónica | Comportamento conservado |
| --- | --- | --- |
| runtime.gguf | model_factory.gguf_inspection | Lectura limitada de metadatos, erros e tipos |
| runtime.model_scout | model_factory.model_scout | Inventario, SHA-256, caché e confinamento de rutas |
| runtime.deployment_validation | deploy.deployment_validation | Hash declarado, elegibilidade e fingerprint |
| runtime.deployment_store | deploy.deployment_store | JSON, snapshots compartidos, rollback e sincronización |

Os módulos antigos son aliases da mesma instancia de módulo, incluídos os
globais que usan as probas e consumidores antigos. A API importa directamente
as implementacións canónicas. Non cambian endpoints nin esquemas persistidos.
A validación de despregamentos segue lendo os bytes sen usar a caché de hashes.

## Validación

Antes do movemento: 16 probas de GGUF, inventario, validador, almacén e contratos.
Despois: executar esas probas, límites GGUF, controlador, API administrativa e
as novas comprobacións de identidade de módulos e monkeypatch do hash.
Ruff e os contratos F0 deben pasar sen modificar as súas referencias.

## Pendentes

`readiness` continúa dependendo de eventos, outbox e procedencia de runtime.
Debe trasladarse despois de resolver esas dependencias en F4i. Este paso non
certifica pesos, non cambia o servizo activo e non promociona modelos.
