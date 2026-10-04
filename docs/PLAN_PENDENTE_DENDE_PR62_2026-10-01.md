<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Auditoría e plan do pendente dende a PR #62

Data: 2026-10-01 · Base: `integration/hydra-1.0` en `ff20bde` (merge da #62) · PR aberta: #63.
Complementa `docs/PLAN_UNIFICACION_LINEAS_2026-10-01.md`: alí está o porqué; aquí está a orde e o
detalle do que falta.

## Avance (revisado o 2026-10-02)

| Paso | Estado |
|---|---|
| P0 1.1 regresión da #63 (repositorios aniñados e `.`) | ✅ #63 (`b48b7ba`: percorre entradas enumeradas polo servidor, rexeita symlinks e junctions) |
| P0 1.2 alerta 70 de CodeQL | ✅ pechada; 0 alertas abertas en `integration` |
| P0 1.3 CodeQL en PRs apiladas | ✅ `pull_request` sen filtro de ramas |
| P0 1.4 auditoría §14 | ✅ esta PR |
| F4b sandbox de verificación e workspaces | ✅ #63 |
| F4j despregamentos (`hydra/deploy/`) | ✅ #65–#68 |
| F4i-1/2 eventos durables, outbox, procedencia e despachador común | ✅ #69, #70 |
| F4g-1 admisión de artefactos e almacenamento de candidatos do corpus | ⏳ #71 (aberta) |
| F4c observabilidade | ✅ #72 |
| F4d/F4e policy e ferramentas | ✅ #73: `Workspace` (confinamento de rutas, o único en produción) → `hydra.tools.task_workspace.ConfinedRoot`; o resto, candidato a retirar (D2, táboa en §2.1) |
| F4k-1 bucle de código e replay de auditoría | ✅ #74: `code_context`, `patching`, `coding_request`, `workspace_hash` → `hydra/coding/`; `replay`, `replay_integrity`, `replay_executor` → `hydra/audit/`. `code_agent` e `code_replay` esperan a F4i (artefactos) e F5 (provedor `LocalLLM`), para non volver importar o runtime dende a plataforma |
| F4i-3 / F4g-2 almacén de tarefas, privacidade, publicacións e calidade de parches | ✅ #75, #76 (Codex) |
| F4h-1 fábrica: variantes físicas | ✅ #77: 16 módulos (construír, executar, medir, seleccionar, promover, rexistrar) → `hydra/model_factory/physical/`. Homónimos de `model_factory/manifest` (`ModelVariant`, `BenchmarkResult`), `optimizer.pareto_frontier` e `training/autoquant.AutoQuant`: distintos modelos de variante, non se fusionan (D6) |
| F4g-3 / F4i-4 captura e crenzas | ✅ #78: `runtime/beliefs` → `world/task_beliefs` (homónimo de `world.model.Belief`), `runtime/learning_capture` → `corpus/patch_capture`; **fallo corrixido**: no gateway, `WorldBeliefStore` descartaba o log compartido e escribía as crenzas nun ficheiro local |
| F4k-2 axente de código | ⏳ esta PR: `provider.LocalLLM` → `providers/local_llm`; `code_agent`, `code_replay`, `coding_loop`, `static_analysis` → `hydra/coding/`; `replay_runtime` → `audit/deployment_replay` |
| `hydra/runtime/` | 98 módulos e 5.822 liñas (antes 7.837) |

## 0. Estado actual (auditado)

| Ámbito | Estado |
|---|---|
| F0 garda de contratos (HTTP, CLI, símbolos, imports plataforma → runtime) | ✅ fusionado |
| F1 configuración e autenticación únicas | ✅ fusionado |
| F2 duplicados pequenos (e homónimos documentados) | ✅ fusionado (#61) |
| F3 / F3e todo o estado durable en PostgreSQL / S3 | ✅ fusionado |
| F6a varias réplicas en Kubernetes | ✅ fusionado (#60) |
| F4a verificador único | ✅ fusionado (#62) |
| F4b sandbox de verificación, `code_verification`, workspaces por tarea | ⏳ PR #63 aberta, **con regresión** (ver 1.1) |
| CI e CodeQL en `integration/hydra-1.0` | ✅ verde en `02f0b4f`; **unha alerta aberta** (ver 1.2) |
| `hydra/runtime/` | 97 módulos e 7.837 liñas; 12 son reexportacións |

**Módulos do runtime sen ningún chamador de produción** (só os usan os seus propios tests):
`autoquant`, `benchmark_protocol`, `build_supervisor`, `variant_runner`, `quality_eval`,
`dataset_factory`, `physical_registry`, `coding_loop`, `replay_runtime`, `static_analysis`,
`tool_audit` e `deployment_resolver` (este último, reexportación). A maioría son pezas da **fábrica**.
Polo principio 0 do plan, ningún se borra sen saber antes se a plataforma xa cobre a súa función.

## 1. Prioridade 0: antes de seguir

### 1.1 Corrixir a regresión da PR #63
Os commits `af7e5ac` e `8cdca98` (Auto-fix, para CodeQL) fan que `TaskWorkspaceManager.create` só
acepte **fillos directos** de `source_root`. Pero `resolve_repository` (`/hydra/v1/coding/verify-fix`)
devolve calquera directorio dentro da raíz, incluídos os aniñados (`org/repo`) e a propia raíz.

1. Aceptar calquera directorio contido en `source_root` (xa o garante `confine`), sen esixir que sexa
   fillo directo. Seguir rexeitando os symlinks no camiño e a orixe que estea fóra da raíz.
2. Engadir tests: repositorio aniñado `org/repo` aceptado, raíz `.` (decidir se se acepta), symlink
   intermedio rexeitado e `../` rexeitado.
3. Comprobar que CodeQL segue sen alertas (o `confine` é o sanitizador).
4. Corrixir a orde dos imports en `task_workspace.py` e a descrición da PR, que xa non é "sen cambios
   de comportamento": agora valida a orixe contra a raíz de repositorios.
5. Fusionar a #63 coa CI comprobada check a check.

### 1.2 Pechar a alerta de CodeQL que se coou en `integration`
`py/clear-text-logging-sensitive-data` en `hydra/core/keystore.py:185` (alerta 70). Entrou ao fusionar
#58–#60, que estaban apiladas e non pasaron CodeQL. A corrección xa está na #63 (commit `9e29986`): péchase ao
fusionala. Despois, comprobar que a alerta queda en "fixed".

### 1.3 Proceso: CodeQL tamén nas PRs apiladas
CodeQL só se lanza contra `main` e `integration/**`, e cambiar a base dunha PR non o relanza.
- Opción A (recomendada): en `codeql.yml`, `pull_request` sen filtro de `branches`.
- Opción B: non apilar PRs. Ou, ao cambiar a base, forzar un novo run e comprobalo antes de fusionar.

### 1.4 Actualizar a auditoría
En `AUDITORIA_INTEGRAL_REPO_2026-10-01.md` §14, a fila "H-06 (resto) / H-07 (resto)" segue como
"Documentado", aínda que xa está feita (F3/F3e). Pasala a ✅ con referencia ás PRs #41–#60.

## 2. F4: fusionar o comportamento (motor e fábrica)

Regras de cada paso: inventario de funcións → tests de caracterización da versión que desaparece →
a que se queda cobre todo → reexportación → F0 sen cambios (salvo engadidos) → unha PR, CI verde.

| Paso | Que | Contido | Risco |
|---|---|---|---|
| **F4c** | Observabilidade | `runtime/observability.CognitiveTracer` (spans ao `TraceStore`/`runtime_spans`) fronte a `observability/tracing.CognitiveTracer` (OTLP, rexistro). Unha soa interface de span con dous destinos: OTLP se hai colector, e o resumo en PostgreSQL. `operating_metrics` le dese tracer | Medio |
| **F4d** | Policy | `runtime/policy` (`ToolPermission`, `PolicyDenied`, `authorize`) fronte a `governance/policy_dsl` + `policy/kernel`. Expresar as permisións de ferramenta do runtime como regras do DSL. Caracterizar cada denegación actual | Medio |
| **F4e** | Ferramentas | `runtime/tools`, `tool_runtime`, `tool_audit` (sen chamadores) fronte a `tools/registry` + `ToolExecutor`. Mapear `ToolSpec` → `ToolDefinition` e conservar a auditoría de cada chamada | Medio |
| **F4f** | Planificador | Tres `ExecutionPlan` (`runtime/planner`, `scheduler/planner`, `planning/goals`) e `runtime/router`. Un único modelo de plan con adaptadores. Caracterizar `Planner.build(task, route)` do runtime | Alto |
| **F4g** | Corpus e datasets | `runtime/corpus` (`CorpusGate`: dereitos + privacidade + tier; `corpus_quality`, `privacy`, `learning_capture`) fronte a `corpus/gates.CorpusCurator`. Pasar as regras do `CorpusGate` ao curador como regras propias, sen relaxar ningunha. `runtime/dataset_factory` (sen chamadores) fronte a `corpus/factory`: comprobar que a plataforma cobre "só CURATED e sen duplicados" e retiralo | Alto |
| **F4h** | Fábrica de modelos (o paso máis grande) | Inventario función a función de `runtime/model_factory` (`ModelVariant`, `BuildState`, `ModelLineage`: usados por despregamentos e `deploy_bridge`; `ModelFactoryLedger` sen uso), `gguf`, `llama_factory`, `quant_profiles`, `model_scout`, `benchmarking`/`benchmark_suite`/`benchmark_protocol`, `pareto`, `optimization_report`, `quality_eval`, `variant_runner`, `build_supervisor`, `promotion`/`promotion_gate`, `physical_registry`, `autoquant` fronte a `model_factory/*`, `training/*` e `edge/autobuild`. Para cada un: **integrar** (se aporta algo que a plataforma non ten), **conectar** (se debería usarse e non se usa) ou **retirar** (se a plataforma xa o cobre). Unha PR por subgrupo: identidade e linaxe; GGUF e cuantización; benchmark e Pareto; promoción; supervisores | Alto |
| **F4i** | Artefactos, procedencia, eventos, crenzas e outbox | O `ArtifactStore` do runtime (rexistros con `kind`/`media_type`) dentro do da plataforma (xa comparten os blobs). Cadea de procedencia do runtime fronte a `provenance/engine` + ledger (manter a ancoraxe). Crenzas: xa van ao World Model no gateway; retirar o `BeliefStore` solto. Outbox: mesma clase `TransactionalOutbox`; unificar o despachador de topics | Medio |
| **F4j** | Despregamentos | `deployment_*`, `traffic_router`, `runtime_health*`, `runtime_evidence`, `health_gate`, `readiness`: non teñen equivalente na plataforma. Movelos tal cual a `hydra/deploy/` (só mover código) | Baixo |
| **F4k** | Bucle de código e replay de auditoría | `code_agent`, `code_context`, `patching`, `coding_request`, `workspace_hash` → `hydra/coding/`; `coding_loop` e `static_analysis` (sen chamadores) → integrar ou retirar. `replay`, `replay_executor`, `replay_integrity`, `code_replay` → `hydra/audit/` (xa existe `hydra/replay.py`, que é outra cousa: o laboratorio de melloras) | Medio |
| **F4l** | Tradución e glosarios do runtime | Non son alcanzables desde o gateway (gaña a plataforma). Retiralos tras a decisión D1 | Baixo |

### 2.1 Candidatos a retirar: subsistema de ferramentas do runtime (D2)
`runtime/policy` (`PolicyEngine`, `ToolPermission`), `runtime/tools` (`ToolRegistry`, `ToolSpec`),
`runtime/tool_runtime` (`ToolRuntime`) e `runtime/tool_audit` só os usan os seus tests. A plataforma
cobre cada función:

| Runtime | Plataforma |
|---|---|
| `workspace.list` | `workspace.list` |
| `workspace.search` | `workspace.search` |
| `workspace.read` (ata 100 000 caracteres) | `filesystem.read` (rutas confinadas por `allowed_path`) |
| `python.test` (pytest no sandbox OCI, só lectura) | `python.run_tests` (sandbox da plataforma); o pytest OCI segue en `tools/oci_sandbox` para o bucle de código |
| `PolicyEngine.authorize` (rede, escritura, execución) | `ToolPolicyEngine.evaluate`: capacidades, nivel de risco, aprobacións, rutas, dominios, modo privado e shadow |
| `tool_audit` | eventos `TOOL_*` do bus e ledger |

Proposta: retiralos en F6b xunto coas reexportacións, salvo que D2 diga o contrario.

## 3. F5: kernel e contratos
Depende da decisión D1.
1. Caracterizar as rutas do runtime que segue servindo o gateway: `/v1/chat`,
   `/hydra/v1/tasks/route|execute`, `/hydra/v1/coding/verify-fix`, `/ready`, admin. Esquemas,
   códigos e eventos emitidos.
2. Facer que `runtime/kernel`, `executor`, `runtime_executor`, `runtime_bridge`, `physical_inference`,
   `provider`, `contracts` e `state` usen o kernel da plataforma (`core/kernel`, `core/task`,
   `core/contracts`) a través dun adaptador que conserve os esquemas.
3. `/v1/chat`: alias de `/v1/chat/completions` ou retirada, segundo D1.
4. `/hydra/v1/tasks/execute`: usar o verificador por capas (`verify`) en vez de só `verify_text`. É un
   cambio de comportamento deliberado e documentado.

## 4. F6b: peche
1. Unha versión despois das reexportacións, borralas (`hydra/runtime/*.py` reexportados e despois o
   paquete) e actualizar `cross_imports.json` (debe quedar baleiro).
2. Facer `HYDRA_RUNTIME_DIR` opcional: só para workspaces por tarea e modo ficheiro.
3. `/ready` sen depender de `llama-server` cando non hai despregamentos físicos; usala de novo na
   readinessProbe.
4. Versión 1.2.0, CHANGELOG e guía de migración (variables novas, `hydra keys export`, adopción
   automática de ficheiros, `HYDRA_REQUIRE_SHARED_STATE`).
5. Pechar §6 da auditoría.

## 5. Ocos coñecidos, fóra de F4/F5

| Oco | Proposta |
|---|---|
| `TradeSecretVault` (IP) segue en ficheiros e non se instancia en produción | Ao conectalo, contido cifrado e ACL nun documento compartido |
| Os brazos dos experimentos do lab mídense no nodo que serve o tráfico | Agregar as métricas dos brazos como contadores sumables (como a memoria de fallos) |
| `edge sync`: se falla a metade da importación, os deltas xa aplicados non quedan marcados | Marcar cada delta á vez que se aplica, ou facer `apply` idempotente por hash |
| O restore deixa os streams `runtime/*` en `data/runtime/`, non en `HYDRA_RUNTIME_DIR` | En PostgreSQL non importa (adóptanse); en modo ficheiro, restaurar a `HYDRA_RUNTIME_DIR` |
| En modo ficheiro, `HYDRA_RUNTIME_DIR` non entra no backup | Incluílo cando estea fóra de `data/` |
| Táboas reservadas antigas (`corpus_records`, `world_*`, `inventions`, `artifacts`) | Migración opcional `DROP TABLE IF EXISTS` documentada; nunca automática |
| Clúster: fai falta unha storage class RWX | Documentar as opcións por provedor; S3 para os blobs reduce o uso de RWX |
| Trazas | Resumo en PostgreSQL feito; OTLP opcional se se monta un colector |

## 6. Accións túas (operación, fóra do código)

1. **Copia local:** `D:/HYDRA` segue en `fix/auditoria-integral-2026-10-01`, 38 commits por detrás de
   `integration/hydra-1.0`, e cun commit local sen subir (`209df9e`, MinIO en compose). Subilo nunha
   PR ou pasalo a `integration`, e actualizar a copia.
2. **Extras:** `pip install -e ".[postgres,s3]"` no entorno do gateway.
3. **MinIO:** copiar as variables de `C:\Users\mejil\.hydra\minio-hydra.env` ao `.env`. Sacar
   `data/secrets/minio.env` (credenciais root) de `data/`; xa non entra nos backups, pero non debe
   estar aí.
4. **Antes do primeiro arranque con PostgreSQL:** `hydra backup --include-private-keys`.
5. **Despois de despregar o gateway novo:** rotar as claves de cliente (`manage_client_keys celtia
   --rotate` e `nova-ai --rotate`) e entregar os `.env` novos.
6. Definir `HYDRA_ADMIN_TOKEN` nos entornos remotos e reconstruír a imaxe do sandbox.
7. **Kubernetes:** storage class RWX, `hydra keys export` coas claves **actuais** e o Secret
   `hydra-keys`.

## 7. Decisións (resoltas para F5)

O propietario delegou a decisión en Codex. Resolución e orde de implementación:
[DECISIONS_F5_2026-10-02.md](DECISIONS_F5_2026-10-02.md).
As recomendacións históricas da táboa seguinte quedan substituídas por esa
resolución: D1 conserva contratos, D2 retira por etapas, D3 acepta a raíz e
D6 mantén variantes separadas. D4 e D5 conservan a recomendación.

| ID | Pregunta | Recomendación |
|---|---|---|
| D1 | Alguén externo usa `/v1/chat`, `/hydra/v1/tasks/*` ou `/hydra/v1/coding/verify-fix`? Hai algún uso do runtime fóra do gateway (`uvicorn hydra.runtime.api:app`)? | Se non: alias durante unha versión e retirada en F6b |
| D2 | Os 12 módulos sen chamadores: integrar, conectar ou retirar? | Decidir módulo a módulo en F4h/F4k, cunha táboa función → implementación na plataforma |
| D3 | Raíz `.` en `resolve_repository` como repositorio válido? | Non: só subdirectorios |
| D4 | Agregar entre nodos as métricas dos brazos do lab? | Si, como contadores sumables |
| D5 | Borrar as táboas reservadas antigas? | Só cunha migración manual documentada |
| D6 | Unificar a variante física (`contracts.ModelVariant`) e a do router (`manifest.ModelVariant`) nun só modelo? | Non agora: son dous ciclos de vida distintos (artefacto despregado fronte a candidato que optimiza o router). Revisalo en F5 |

## 8. Orde e tamaño estimado

1. P0: #63 corrixida e fusionada, CodeQL en PRs apiladas, auditoría actualizada (2 PRs).
2. F4j e F4k (mover código sen cambiar comportamento: baixo risco, reducen moito `hydra/runtime`) (2–3 PRs).
3. F4c, F4d, F4e e F4i (4 PRs).
4. F4g e F4h (corpus e fábrica: inventario + 4–6 PRs).
5. F4f e F5 (planificador e kernel, tras D1) (3–4 PRs).
6. F6b peche (2 PRs).

Total: uns **17–21 PRs**. Ningunha mestura mover código con cambiar comportamento, e todas pasan
F0 + CI completa + CodeQL antes de fusionar.
