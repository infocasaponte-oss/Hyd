<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Decisións para continuar F5

O propietario delegou a decisión en Codex. Estas decisións desbloquean o plan;
non certifican modelos nin autorizan a eliminación automática de datos.

## D1: conservar contratos, converxer nun kernel

Tratar como públicas `/v1/chat`, `/hydra/v1/tasks/route`,
`/hydra/v1/tasks/execute` e `/hydra/v1/coding/verify-fix`. Conservar tamén
`uvicorn hydra.runtime.api:app` como entrada de compatibilidade durante unha
versión despois de introducir a entrada canónica substituta.

Non hai evidencia suficiente para afirmar que ninguén as usa externamente.
`api/runtime_routes.py` monta estas rutas e `runtime/api.py` define esquemas,
autenticación e efectos que non equivalen aos da API OpenAI. A documentación
e as probas tamén as consideran contratos estables. Esa evidencia xustifica
preservalas; non demostra consumidores concretos.

O destino é un kernel de plataforma cunha fachada de compatibilidade, non
dous kernels permanentes. Conservar request/response, códigos, tokens e rate
limits, eventos, artefactos, selección física, captura e límites de políticas.
Non converter `/v1/chat` nun alias HTTP directo de `/v1/chat/completions`.

Orde de implementación:

1. Caracterizar as catro rutas e o arranque separado, incluídos erros e efectos.
2. Integrar router/planificador mediante adaptadores que preserven os plans e
   contratos. Separar a decisión de routing da execución.
3. Integrar executor e selección física no kernel canónico, conservando a
   política de fallback e a persistencia transaccional.
4. Conectar as rutas á fachada sobre ese kernel. F0, regresión e probas de
   ambos arranques deben pasar antes de retirar implementacións duplicadas.
5. Publicar migración e manter os imports antigos durante unha versión.
   Retirar fachadas só tras esa xanela e unha comprobación explícita de usos.

O cambio de verificador de texto ao verificador por capas é unha PR distinta:
cambia comportamento e require tests propios; non se oculta nun traslado.

## D2: retirar o subsistema antigo de ferramentas por etapas

Aprobar a retirada da implementación duplicada de `runtime.tools`,
`runtime.tool_runtime`, `runtime.tool_audit` e `runtime.policy`. A busca nos
imports de produción só atopou dependencias entre estes módulos; as probas
seguen importándoos. Non conectar este subsistema ao gateway para xustificar
a súa existencia.

Antes de eliminar código, inventariar cada operación e denegación e comparar
coa plataforma. Os adaptadores deben conservar a prohibición de execución
no host, permisos de rede/escritura/execución, confinamento, timeout, saída e
auditoría. `Workspace` segue sendo un alias de `ConfinedRoot`.

Durante unha versión conservar nomes públicos e probas de compatibilidade.
Se unha función aínda non está cuberta, integrala primeiro; non borrala só
porque non teña chamadores. Eliminar os shims en F6b, nunca agora saltando F0.

## D6: variantes separadas e conversión explícita

Conservar `model_factory.contracts.ModelVariant` para artefactos físicos e
`model_factory.manifest.ModelVariant` para candidatos de optimización do
router. Teñen ciclos de vida distintos. Non unificar estados, identificadores
ou esquemas por compartir o nome; o paso entre ambos debe validar capacidades,
procedencia, artefacto, estado de promoción e resultados de avaliación.

## Outras decisións

- D3: aceptar a raíz `.` e repositorios aniñados, co confinamento comprobado
  na #74. É o contrato actual, conservado deliberadamente.
- D4: agregar métricas entre nodos mediante contadores compartidos cando se
  implemente ese paso; non usar métricas dun nodo como resultado do clúster.
- D5: non borrar táboas automaticamente. Calquera limpeza require unha
  migración operativa explícita e backup.

## Límites desta resolución

Este documento resolve decisións de arquitectura, non executa F5 enteiro.
Non altera CeltIA, claves, servizos activos, corpus ou pesos. F6b e a versión
1.2.0 seguen condicionadas á implementación e validación anteriores.
