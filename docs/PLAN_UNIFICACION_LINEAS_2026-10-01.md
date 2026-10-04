<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Plan de unificación: línea de plataforma y línea runtime (HYDRA-SO)

Fecha: 2026-10-01 · Rama base: `integration/hydra-1.0` (`df57f28`) · Origen: auditoría integral, §6.

## 1. Objetivo y criterio de terminado

Una sola línea de código bajo `hydra/` en la que:

1. Todo el estado persistente vive en almacenes compartibles entre nodos: PostgreSQL, logs de
   `hydra_logs` y blobs en S3 o en un volumen compartido. Nada queda en `HYDRA_RUNTIME_DIR`.
2. Cada concepto tiene una única implementación: Settings, kernel, contratos, verificador,
   planificador, sandbox, corpus, artefactos, creencias, outbox y trazas.
3. La API pública no cambia de forma incompatible. Las rutas que hoy sirve el runtime siguen
   respondiendo igual, como mínimo durante una versión de transición.
4. Los manifiestos CLUSTER pueden subir a más de una réplica por servicio.

Hoy se cumple el punto 1 para la plataforma (PRs #41–#50). Este plan cubre el resto.

## 2. Inventario (estado real del código)

### 2.1 Tamaño y acoplamiento

* `hydra/runtime/`: 96 módulos y unas 7.600 líneas. Cuatro ya son reexportaciones de la plataforma:
  `circuit_breaker`, `hardware`, `language` y `rate_limit`.
* Tests: 93 ficheros en `tests/runtime/` y 9 ficheros fuera de esa carpeta que importan `hydra.runtime`.
* El gateway monta las 21 rutas de `hydra/runtime/api.py` mediante `api/runtime_routes.py`. Si una
  ruta coincide en método y path con una de la plataforma, gana la plataforma. Según el docstring de
  `runtime_routes.py`, quedan servidas por el runtime estas:
  `/ready`, `/v1/chat`, `/hydra/v1/tasks/route|execute`, `/hydra/v1/admin/*` (métricas, despliegues
  shadow/canary/activate/rollback/evidence, outbox, replay audit), `/hydra/v1/coding/verify-fix` y
  `GET /hydra/v1/models/artifacts`, que es el `/v1/models` del runtime reubicado.
* Partes de la plataforma que importan el runtime:

  | Módulo de plataforma | Qué importa del runtime |
  |---|---|
  | `api/platform_routes.py` | `BudgetExceeded`, métricas del outbox del runtime |
  | `edge/translation.py` | `RequestBudget` |
  | `edge/autobuild.py` | `PeakVramMonitor` |
  | `model_factory/deploy_bridge.py` | `ModelVariant`, `PromotionPolicy`… |
  | `planning/runner.py` | `changed_python_paths` |
  | `world/runtime_beliefs.py` | `BeliefStore` |
  | `core/capture_outbox*.py` | outbox y worker |

* Partes del runtime que importan la plataforma: `tools.workspace`, `corpus.gates`,
  `model_factory.gguf`, `edge.profiles`, `governance.rate_limit` y `registry.circuit_breaker`.

### 2.2 Estado en disco del runtime (`HYDRA_RUNTIME_DIR`)

| Fichero o carpeta | Módulo | Destino propuesto |
|---|---|---|
| `events.jsonl` (cadena hash) | `runtime/events.py` | ✅ F3a: stream `runtime/events.jsonl` (`HYDRA_RUNTIME_BACKEND`); secuencia, hash previo e idempotencia resueltos con el stream bloqueado |
| `provenance.jsonl` (cadena hash) | `runtime/provenance.py` | ✅ F3a: stream `runtime/provenance.jsonl`; el anclaje en el ledger (`ledger/runtime_anchor.py`) se mantiene |
| `runtime-evidence.jsonl` | `runtime/runtime_evidence.py` | ✅ F3b: stream `runtime/evidence.jsonl` (la evidencia de todos los nodos cuenta); fases por `seq`; los offsets en bytes de despliegues a mitad de fase se convierten al arrancar y, si el fichero ya no está, la fase vuelve a contar desde ese momento (`evidence_restarted_at`) |
| `deployments.json` | `runtime/deployment_store.py` | ✅ F3b: snapshots en `runtime/deployments.jsonl`; cada operación de admin es `mutate` sobre el último estado con el stream bloqueado; los nodos siguen el registro con `sync` cada segundo; un fallo a medias restaura la memoria; `deployments.json` se adopta una vez |
| `hydra.db` → `outbox`, `task_commits` | `runtime/outbox.py`, `capture_uow.py` | ✅ F3c: `runtime_outbox` (el `PostgresOutbox` de captura, con reclamación por nodo) y `task_commits` en la misma transacción (`runtime/pg_stores.py`) |
| `hydra.db` → métricas, salud, evidencia de despliegue | `metrics_store`, `runtime_health_store`, `deployment_evidence_store` | ✅ F3c: tablas `operating_metrics` (con el nodo), `runtime_health` (por nodo y variante: la salud de un runtime vista desde un nodo no vale para otro) y `deployment_evidence`; `hydra.db` se importa una vez |
| `beliefs.jsonl` | `runtime/beliefs.py` | ✅ F3d: en el gateway van al World Model (`world/runtime_beliefs.py`); el runtime suelto las escribe en el stream `runtime/beliefs.jsonl` |
| `corpus.jsonl` | `runtime/corpus.py` | ✅ F3d: stream `runtime/corpus.jsonl` con su modelo propio (puerta de derechos y privacidad); `append_once` comprueba el hash con el stream bloqueado. Fusionar con `corpus.store` cambia comportamiento: F4 |
| `artifacts/` | `runtime/artifacts.py`, `replay_executor.py` | ✅ F3d: blobs en el almacén de la plataforma (`HYDRA_ARTIFACT_OBJECTS`: volumen o S3) y manifiestos en `runtime/artifacts.jsonl`; los blobs locales anteriores se siguen leyendo y se copian al almacén compartido la primera vez; la auditoría de replay re-hashea en el almacén compartido |
| `datasets/`, `optimization/`, `replay/` | `dataset_factory`, `optimization_report`, `replay` | ✅ F3d `replay/`: stream `runtime/replay.jsonl` (los manifiestos anteriores se siguen leyendo). `DatasetFactory` y `OptimizationReportStore` del runtime no se instancian en producción (las funciones de la fábrica las sirve `corpus/factory` y `model_factory` de la plataforma): se fusionan en F4 |
| `model_factory.jsonl` | `runtime/model_factory.py` | `ModelFactoryLedger` no tiene ningún uso (ni tests); `ModelVariant`/`BuildState` sí (despliegues, `deploy_bridge`). Se decide en F4 con la factoría de la plataforma |
| `glossaries/` | `runtime/translation.py` | No alcanzable desde el gateway: la plataforma sirve `/v1/translate` y `/v1/glossaries` con su propio almacén. Se retira en F4 |
| `workspaces/` | `runtime/workspaces.py` | `tools.workspace.WorkspaceManager`, por tarea y efímero, en volumen local por pod (no necesita compartirse) |
| `traces.jsonl` | `observability.py`, `operating_metrics.py` | ✅ F3e-2: con PostgreSQL, tabla `runtime_spans` (todos los nodos, acotada) y las métricas de operación son del clúster; el JSONL queda para el modo fichero. OTLP (`HYDRA_OTEL_ENDPOINT`) sigue disponible si se monta un colector |

### 2.3 Subsistemas duplicados (de §6 de la auditoría, con decisión)

| Concepto | Se queda | Se absorbe | Nota |
|---|---|---|---|
| Settings | `core/config.Settings` | `runtime/config` (dataclass + `os.getenv`) | F1: `runtime/config.Settings` es una vista congelada de la de plataforma (`from_platform`), con las mismas variables y valores por defecto; `HYDRA_API_TOKEN` sigue como alias de `HYDRA_API_KEY` |
| Seguridad | `api/security` | `runtime/security` | F1: el acceso API del runtime usa `authenticate` del gateway (claves por cliente incluidas). El admin del runtime sigue más estricto a propósito: exige `HYDRA_ADMIN_TOKEN` configurado incluso en loopback |
| `BudgetExceeded` / budgets | `core/budget` | `runtime/budgets` | hoy `platform_routes` importa el del runtime |
| Hash e IO (5 funciones de hash de fichero) | `core/hashing` | `runtime/hash_chain`, helpers sueltos | |
| Traducción | `edge/translation` | `runtime/translation` | la plataforma ya sirve `/v1/translate` |
| Artefactos | `artifacts/store` | `runtime/artifacts` | |
| Provenance | `provenance/engine` + `ledger/chain` | `runtime/provenance` | la cadena del runtime se conserva como stream y anclaje |
| Corpus y datasets | `corpus/store`, `corpus/factory` | `runtime/corpus`, `runtime/dataset_factory` | `runtime/corpus_quality` se mantiene como puerta de calidad |
| Creencias | `world/model` | `runtime/beliefs` | |
| Outbox | `capture_outbox` (+ PG) | `runtime/outbox` | un solo outbox con topics |
| Sandbox y workspaces | `tools/sandbox`, `tools/workspace` | `runtime/sandbox`, `runtime/workspaces` | ✅ F4b: no se solapan. `tools/sandbox` ejecuta fragmentos de Python; el del runtime ejecuta py_compile/ruff/mypy/pytest sobre el workspace de la tarea → movido tal cual a `tools/oci_sandbox` (misma imagen), con `code_verification` → `verification/code` y las copias por tarea → `tools/task_workspace`; el runtime reexporta |
| Verificador | `verification/verifier` | `runtime/verifier`, `code_verification` | ✅ F4a: `Verifier.verify_text` (+ `TextVerification`) reproduce la verificación estructural del runtime, comprobada idéntica contra el original; `runtime/verifier` reexporta. `code_verification` va con el sandbox (depende de `SandboxResult`) |
| Planificador | `scheduler/planner` | `runtime/planner`, `planning/goals.ExecutionPlan` | tres `ExecutionPlan`: unificar a uno |
| Policy y herramientas | `governance/policy_dsl`, `tools/policy.ToolPolicyEngine`, `tools/*` | `runtime/policy`, `runtime/tools`, `tool_runtime`, `tool_audit` | F4d/F4e: solo `Workspace` (confinamiento) se usa en producción → `tools/task_workspace.ConfinedRoot`; el resto lo cubre la plataforma y es candidato a retirar (D2) |
| Observabilidad | `observability/tracing` | `runtime/observability` | ✅ F4c: homónimos. `observability/tracing.CognitiveTracer` sigue los eventos del bus (OTLP GenAI, Prometheus, flamegraph); el del runtime registra pasos con un context manager → `observability/spans.SpanRecorder` (más exportación OTLP opcional en segundo plano), `observability/operating` y `operating_store`; el runtime reexporta |
| Registry y factoría de modelos | `registry/*`, `model_factory/*` | `runtime/model_registry`, `model_factory`, `autoquant`, `gguf`, `llama_factory` | `deploy_bridge` ya hace de puente |
| Kernel y contratos | `core/kernel`, `core/task`, `core/contracts` | `runtime/kernel`, `runtime/contracts` | lo último (F5) |

**Sin equivalente en la plataforma:** se mueven tal cual a paquetes de plataforma.

* Controlador de despliegue con shadow/canary y su evidencia medida (`deployment_*`, `promotion*`,
  `traffic_router`, `runtime_evidence`).
* Replay e integridad (`replay*`).
* Bucle de código (`coding_loop`, `code_agent`, `code_context`, `code_replay`, `patching`, `static_analysis`).
* Model scout, benchmarking, Pareto y quality eval.
* Supervisores de proceso y build, startup recovery, readiness y health gate.

Destino propuesto: `hydra/deploy/`, `hydra/replay/`, `hydra/coding/` y `hydra/model_factory/`.

## 3. Principios

0. **El repo contiene dos productos: el motor HYDRA y la fábrica de motores.** La fábrica abarca
   `model_factory`, entrenamiento, autobuild, GGUF/cuantización, benchmarking, scout y promoción.
   Al quitar un duplicado, la implementación que se queda debe cubrir **todas** las funciones de las
   dos, en el motor y en la fábrica. Antes de absorber un módulo se inventarían sus usos en ambos
   productos y se escriben tests de caracterización de la versión que desaparece. Solo después pasa
   a ser una reexportación.
1. **La plataforma es la base.** Ya tiene los backends compartidos y la mayor cobertura. El runtime
   aporta lo que la plataforma no tiene.
2. **Un PR por paso, todos en verde.** Suite completa y job de integración con PostgreSQL. Ningún
   paso deja dos implementaciones activas del mismo estado.
3. **Compatibilidad por reexportación.** El módulo absorbido queda como reexportación durante una
   versión y se borra en la siguiente, que es el patrón que ya existe.
4. **Las rutas no cambian.** Un test de contrato fija el OpenAPI de las rutas montadas (paths,
   métodos y esquemas) antes de empezar, y cada PR debe mantenerlo.
5. **Los datos existentes se migran solos y una sola vez,** verificados, con el original conservado.
   Es el mismo patrón que ledger, corpus, IP y blobs.
6. **Ninguna importación nueva de `hydra.runtime` desde la plataforma.** Lo vigila un test que
   recorre los imports.

### 2.4 Registros pequeños en `HYDRA_DATA_DIR` (F3e, previo a varias réplicas)

Encontrados al preparar F6: ficheros JSON que cada proceso reescribe enteros (con dos réplicas, el último
en escribir borra lo del otro). **F3e-1 ✅** los pasa a `hydra.core.docstore` (tabla `hydra_documents`,
lectura-modificación-escritura con la fila bloqueada) sin cambiar lo que hace ninguno:

| Producto | Registro | Cómo se escribe ahora |
|---|---|---|
| Motor | `flags.json`, `glossaries.json`, `model_lifecycle.json` | una clave por escritura sobre la última versión |
| Motor | `configs/<env>.jsonl` | log de eventos: la versión se numera con el stream bloqueado |
| Motor | `secrets/secrets.enc`, `policies.json` | documento con el token Fernet (nunca el texto en claro) y otro con las políticas |
| Motor | `lab.json` | por experimento; las métricas vivas las mide el nodo que sirve el tráfico |
| Motor | `failure_memory.json` | cada nodo **suma** sus observaciones a los totales guardados |
| Motor | `edge/applied_deltas.json` | se aplica con el documento bloqueado: un bundle importado por dos nodos aplica cada delta una vez |
| Fábrica | `models/{artifacts,variants,lineage,jobs}.json`, `models/adapters.json` | una entrada por escritura: API y workers de fábrica comparten el registro |

**F3e-2 ✅:** aprendizaje del planificador (`planning/historical.json` y `value.json`: cada nodo suma sus
ejecuciones y recompensas; `calibration.json`: historial común, últimos 500 por clave; `procedures.json`:
versiones, estadísticas y promociones sobre la última lista con el documento bloqueado), propuestas de
mejora (`improvements.json`: los ids `HYDRA-IMP-nnn` se asignan con el documento bloqueado) y trazas del
runtime en PostgreSQL (`runtime_spans`, acotada): `/hydra/v1/admin/metrics` describe el clúster entero.
`TradeSecretVault` (IP) no se instancia en producción.

### 2.5 Homónimos: mismo nombre, conceptos distintos (se conservan)

| Nombre | Uno | Otro |
|---|---|---|
| `BudgetExceeded` | `core/budget`: presupuesto cognitivo agotado durante la tarea (el kernel degrada la respuesta) | `core/request_budget.RequestBudgetExceeded`: la petición excede su tamaño (HTTP 413/400) |
| `CognitiveBudget` | `core/budget`: presupuesto resuelto (todos los campos) | `core/task`: límites opcionales que pide una tarea |
| `HardwareProfile` | `edge/profiles`: ajuste de llama.cpp por GPU | `model_factory/hardware`: máquina para elegir cuantización y formato |
| `SimulationResult` | `planning/simulator`: simulación de una acción del plan | `simulation/engine`: ensayo en seco de una herramienta |
| `Procedure` | `memory/models`: memoria procedimental | `planning/procedures`: procedimiento aprendido y promovido |
| `WorldEvent`/`WorldRelation` | `world/model`: World Model bitemporal | `world/state`: estado provisional de una tarea |
| `_now` | devuelven `datetime` o `str` según el modelo que los usa | |

## 4. Fases

| Fase | Contenido | PRs aprox. | Riesgo |
|---|---|---|---|
| **F0 Guardas** ✅ | `tests/test_contracts.py` y `tests/contracts/`: snapshot de las 140 operaciones HTTP (con las del runtime montadas) y sus esquemas; árbol completo del CLI `hydra` (motor y fábrica); ids de operación únicos; imports plataforma → runtime que solo pueden menguar; y comprobación estática de que todo símbolo `hydra.*` que importan el motor, la fábrica, el runtime y `scripts/` existe | 1 | Bajo |
| **F1 Configuración y auth** ✅ | `runtime/config` derivado de `Settings`; alias de variables; las rutas del runtime usan `api/security.py` (claves por cliente incluidas) | 1–2 | Medio (tokens) |
| **F2 Duplicados pequeños** ✅ | Fusionados los duplicados reales: límites de petición a `core/request_budget` (el runtime reexporta; un import plataforma → runtime menos), `_print`/`_kv` del CLI (`cli_io`), similitud coseno (`core/vectors`), hash de fichero (`core.hashing.sha256_file`) y contador de tokens. **No** fusionados, por ser homónimos de conceptos distintos (fusionarlos quitaría funciones): ver §2.5 | 1 | Bajo |
| **F3 Estado del runtime a almacenes compartidos** | Según §2.2: events y provenance a `hydra_logs`; evidencia a stream con `seq` (los despliegues a mitad de fase convierten su offset de bytes a `seq` al migrar); `deployments.json` a log de versiones; `hydra.db` a tablas PG con reclamación por nodo; creencias, corpus y artefactos del runtime a los de plataforma | 4–5 | **Alto**: es el que cambia formatos en disco |
| **F4 Comportamiento** | Verificador, planificador (un único `ExecutionPlan`), sandbox/workspaces, policy y observabilidad; antes de cada fusión, diff funcional y tests de caracterización de la versión que desaparece | 4–5 | Alto (semántica) |
| **F5 Kernel y contratos** | `/hydra/v1/tasks/route|execute` y `/v1/chat` servidos por el kernel de plataforma (`/v1/chat` como alias de `/v1/chat/completions`), conservando los esquemas | 2 | Alto |
| **F6a Réplicas** ✅ | `hydra-api` ×2 (RollingUpdate, PDB, anti-afinidad preferente) y `hydra-fabric-worker` ×2 sin afinidad de pod; `/data` RWX; claves en el Secret `hydra-keys` (`hydra keys export`); `HYDRA_REQUIRE_SHARED_STATE` rechaza arrancar si algún plano queda local | 1 | Medio |
| **F6 Cierre** | Borrar `hydra/runtime/` (salvo reexportaciones de una versión), `HYDRA_RUNTIME_DIR` opcional, manifiestos k8s a más de una réplica (quitar afinidad de pod y PVC RWO del runtime), documentación | 1–2 | Medio |

Total aproximado: 15–19 PRs. F0–F2 se pueden hacer ya. F3 es el que más valor da, porque libera las
réplicas. F4–F5 necesitan revisión de comportamiento caso a caso.

## 5. Decisiones que necesito de ti

1. **Clientes de las rutas del runtime.** ¿Alguien externo usa `/v1/chat`, `/hydra/v1/tasks/*` o
   `/hydra/v1/coding/verify-fix`? Ni el SDK TypeScript ni Studio (`api/studio.html`) las usan. Si no
   hay clientes, en F5 se pueden retirar en vez de mantenerlas como alias.
2. **Autenticación única.** El runtime ya toma `HYDRA_API_TOKEN` o, en su defecto, `HYDRA_API_KEY`,
   pero tiene su propio `runtime/security.py`, que no acepta las claves por cliente
   (`hydra.<id>.<secret>`). Propuesta: que esas rutas usen `api/security.py` (claves por cliente
   incluidas) y que `HYDRA_API_TOKEN` quede como alias con aviso durante una versión.
3. **Trazas.** ¿Basta OTLP más métricas en PostgreSQL, o hace falta conservar `traces.jsonl` en
   producción?
4. **Orden.** Propuesta: F0 → F1 → F3 → F2 → F4 → F5 → F6. F3 sube antes porque es lo que permite
   escalar réplicas.

**Backup del runtime (F3d):** con PostgreSQL, `hydra backup` exporta los streams `runtime/*` (cadenas,
evidencia, despliegues, corpus, creencias, replay, artefactos) bajo `data/runtime/`, y las tablas de F3c
quedan en el volcado (`pg_dump`). Con ficheros, `HYDRA_RUNTIME_DIR` sigue fuera del backup.

## 6. Riesgos y mitigación

* **Formatos en disco (F3).** Migración verificada al arrancar, original conservado y backup antes
  (`hydra backup --include-private-keys`). Cada almacén tiene su test de adopción y de conflicto.
* **Despliegues a mitad de canary o shadow.** La conversión de offset de bytes a `seq` se prueba
  con un log real, y si un despliegue no puede convertirse vuelve al inicio de su fase con aviso, en
  vez de inventar evidencia.
* **Diferencias de semántica (F4–F5).** Tests de caracterización escritos sobre la implementación
  que se va antes de borrarla, y `tests/runtime/` (93 ficheros) en verde en cada paso.
* **Tamaño de los PRs.** Ningún PR mezcla mover código con cambiar comportamiento.
