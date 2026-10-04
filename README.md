# HYDRA OS 1.1

Construcción local del motor y del candidato `HYDRA.gguf`: [guía, evidencia y estado actual](docs/HYDRA_GGUF_LOCAL.md).

API Python asíncrona `engine.query()`: [uso e integración con el kernel](docs/ENGINE_QUERY.md).

**Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.**
Software propietario — consulte [LICENSE](LICENSE).

HYDRA es un **sistema operativo cognitivo heterogéneo**: los LLM/VLM son unidades de cómputo
reemplazables y el valor está en el kernel, el World Model, el corpus, los procedimientos, las evals,
el linaje de modelos y la procedencia (IP). HYDRA decide *dónde pensar, cuánto pensar, qué herramienta
usar, qué recordar, cuándo preguntar y cuándo parar*; aprende de cada ejecución verificada y puede
fabricar, cuantizar, evaluar y desplegar sus propios especialistas — sin modificarse nunca a sí mismo
en producción.

```text
                          META CONTROLLER
                                │
              ┌─────────────────┼─────────────────┐
           POLICY             ROUTER          SCHEDULER (clúster, KV, SLA)
              └─────────────────┼─────────────────┘
                         COGNITIVE KERNEL
      ┌──────────┬──────────────┼──────────────┬──────────┐
    MODELS     TOOLS         MEMORY         PLANNER    SIMULATOR
      └──────────┴──────────────┼──────────────┴──────────┘
                    WORLD MODEL + BELIEF GRAPH
                  (entidades, relaciones, eventos, tiempo, evidencia)
                                │
                  VERIFIER ── ARTIFACT ENGINE (CAS)
   ─────────────────────── LEARNING PLANE ────────────────────────
   Corpus Engine → Dataset Factory → Synthetic Foundry → Training Lab (SFT/LoRA/DPO/MLX, federado)
   → Model Factory (GGUF/AWQ/FP8/MLX) → Capability Discovery → Eval Arena → Registry
   ───────────────────────── IP PLANE ─────────────────────────────
   Ledger firmado (hash-chain + Merkle) → Invenciones → Licencias → SBOM/ML-BOM → Release Gate
```

## Inicio rápido

```bash
pip install -e ".[all,dev]"
hydra ask "¿Cuánto es 17 × 23?" --offline --sandbox subprocess     # sin GPU ni runtimes
pytest                                                              # ~600 pruebas + integración opcional
hydra serve                                                         # API: /docs · Studio: /studio
```

### Estación local (RTX 3060 Ti / 8 GB, validado)

```bash
set HYDRA_MODELS_CONFIG=config/models.ollama.yaml
set HYDRA_BUDGET_TIME_SCALE=3
hydra edge profile                    # detecta GPU: rtx3060ti · CUDA arch 86 · Q4_K_M · ctx 8K · KV q8_0
hydra edge scout                      # modelos Ollama/GGUF que caben en la GPU + especialistas para CPU
hydra build --auto --model qwen3:8b --apply     # AutoBuilder: mide contextos/offload, elige y firma el manifiesto
hydra goal "Encuentra y corrige el bug" --workspace ./mi-repo
hydra translate "El World Model..." --to portugués --glossary tech
```

`scripts/bootstrap_3060ti.sh` / `scripts/bootstrap_windows.ps1` compilan llama.cpp para la
arquitectura CUDA detectada (`-DCMAKE_CUDA_ARCHITECTURES=86`); `scripts/autobuild.sh` y
`scripts/start_llama_server.sh` aplican y arrancan la configuración ganadora.

## Ciclo de una tarea

`CREATED → ROUTING → RETRIEVING → PLANNING → EXECUTING → VERIFYING → SYNTHESIZING → CAPTURING → COMPLETED`

1. **Policy Kernel** + **Policy DSL** (`config/policy_rules.yaml`): sensibilidad, redacción, prohibiciones,
   modelos permitidos por clasificación, confirmaciones.
2. **Semantic Cache**, **determinista primero** opcional (calculadora, sympy, JSON, SQL: `HYDRA_DETERMINISTIC_FIRST`).
3. **Router** + router aprendido A/B + **reranking de clúster** (residencia HOT, localidad KV, colas, SLA).
4. **RETRIEVING**: memoria (4 tipos) + **Graph RAG** sobre el World Model (filtrado por visibilidad).
5. Planner / ejecución / hedging / escalado; herramientas con **capabilities**, **Secrets Broker**
   (`secret://` nunca llega al modelo) y **frontera de contenido no confiable** (anti-inyección).
6. **Verificador v2**, claims, provenance. Contexto mayor que cualquier ventana → degradación con recorte.
7. **CAPTURING** (capture pipeline): delta al **World Model**, artefactos al **CAS** (`cas://sha256/…`),
   varios registros de **corpus** (en cuarentena), evento firmado en el **ledger**, **flight recorder** y
   *learning snapshot* en la respuesta (`learning`).

## Planos de HYDRA 1.0

| Plano | Qué hace | CLI / API |
|---|---|---|
| **World Model + Belief Graph** | entidades, relaciones bitemporales, eventos, observaciones≠verdad, evidencia por familias de fuente, contradicciones, decaimiento, causalidad, time machine, grafo de código | `hydra world …` · `/hydra/v1/world*` |
| **Planner/Simulator** | objetivos con condiciones, HTN, DAG, simulador en conjunto (reglas/histórico/sandbox) calibrado, Monte Carlo, branch-and-bound, Pareto, ganancia de información, procedimientos versionados, value model (System 1/2), checkpoints | `hydra goal` · `/hydra/v1/goals` |
| **Corpus Engine** | registro universal, privacy/rights gates, calidad Q y tiers, dedup exacto/SimHash/AST/semántico, contaminación, linaje, tombstones con impacto, snapshots | `hydra corpus …` · `/hydra/v1/corpus/*` |
| **Dataset Factory / Synthetic Foundry** | recetas YAML, balanceo, anti-colapso, holdouts temporal/adversarial, compiladores SFT/DPO/KTO/reward/tool/process/planner/value/embedding | `hydra dataset build` |
| **Training Lab** | trazas elegibles, TRL/PEFT/MLX/builtin, orquestador con estados, reward engine, descubrimiento de especialistas con ROI, Eval Arena + regression guard, promotion gate, firma, supply-chain, AutoQuant por tensor | `hydra train …` |
| **Capability Discovery** | ontología, sondeo adaptativo, intervalos de Wilson, huella MEDIDA vs DECLARADA, capacidades emergentes, replacement analyzer, ciclo de vida, Benchmark Exchange | `hydra discover MODEL` |
| **Federado/privado** | FedAvg/mediana, recorte + ruido gaussiano, contabilidad ε, analítica federada k-anónima | `/hydra/v1/federated/analytics` |
| **Scheduler distribuido** | nodos/GPU con heartbeats, residencia y warm pool, admisión con reservas, plan TP/PP/DP/EP, drafts especulativos, fallback de cuantización, degradación, capacidad, economía, SLO, tenants | `hydra cluster …` · `/v1/cluster/*` |
| **Execution Fabric** | colas por prioridad (REALTIME…BACKGROUND_LAB), leases, reintentos, dead-letter, idempotencia, checkpoints | `hydra worker` · `/v1/fabric/*` |
| **IP / licencias / releases** | ledger append-only hash-encadenado y firmado (Ed25519) con anclas Merkle, invenciones, efectos técnicos, contribuciones, prior art, cortafuegos de divulgación, secretos empresariales cifrados, paquete de evidencias, motor de licencias, SBOM/ML-BOM CycloneDX 1.6, Release Gate, releases firmadas y promoción DEV→LAB→STAGING→CANARY→PRODUCTION | `hydra ip/ledger/license/bom/release …` |
| **Gobernanza** | principales y tokens de capacidad, motor de riesgo, ActionEnvelope, config sets versionados, feature flags, Red Team + Chaos, System Contract (10 invariantes), Definition of Done, backup/restore verificado | `hydra redteam` · `hydra doctor` · `hydra backup/restore` |
| **Protocolos** | API nativa `/v1/tasks` (`HydraTask`/`HydraResult`), `/hydra/v1/*`, OpenAI `/v1/chat/completions` `/v1/responses` `/v1/embeddings`, **MCP** servidor (`/mcp`, `hydra mcp`) y cliente, WebSocket de eventos `/v1/ws/tasks`, SDK Python (`hydra.sdk`) y TypeScript (`sdk/typescript`) | |
| **Observabilidad** | spans OTLP con convenciones GenAI, flamegraph cognitivo, atribución de costes, `/metrics` Prometheus, 5 dashboards Grafana | `/hydra/v1/tasks/{id}/flamegraph` |
| **Replay / evolución** | replay auditoría/simulación/contrafactual (`--replace-model a=b`), replay digital de trazas, laboratorio de mejoras (HYDRA-IMP) | `hydra replay …` |
| **Edge** | perfiles de hardware, AutoBuilder, Model Scout, Residency Manager (1 modelo grande en GPU, pequeños en CPU), motor de traducción con glosarios, sincronización firmada edge↔central | `hydra edge/build/translate/sync …` |
| **Studio** | UI web: tareas, World Graph, modelos, corpus, training, infraestructura, IP y sistema | `http://127.0.0.1:8080/studio` |

## System Contract (HYDRA 1.0)

`hydra doctor` comprueba sobre el runtime real los 10 invariantes (ningún modelo actúa directamente,
provenance, hash y linaje, derechos y privacidad, Policy Kernel, evals, releases firmadas, auditoría,
fallos distribuidos limpios, sin auto-modificación) y la **Definition of Done** fila a fila con evidencia
(PASS / PARTIAL / FAIL). `hydra e2e` ejecuta **HYDRA-E2E-100** (100 tareas en 8 categorías).

## Línea runtime HYDRA-SO (integrada en 1.1)

El gateway sirve también la línea HYDRA-SO (`hydra.runtime`, con su historia completa): `/ready`, `/v1/chat`,
`/hydra/v1/tasks/route|execute`, `/hydra/v1/admin/*` (despliegues shadow/canary/rollback, métricas, dead
letters, auditoría de replay) y `/hydra/v1/coding/verify-fix`. Un único token (`HYDRA_API_KEY` o
`HYDRA_API_TOKEN`) protege ambas líneas con las mismas reglas (HTTP y WebSocket; sin token, solo clientes
loopback; las claves por cliente `hydra.<id>.<secret>` solo sirven para inferencia y reciben 403 en el resto).
Las dos líneas leen la misma configuración (`hydra.core.config.Settings`).
`HYDRA_ADMIN_TOKEN` (cabecera `X-Hydra-Admin-Token`) protege además toda operación de operador: rutas
admin del runtime (fallan cerradas sin él) y, en la plataforma, flags, config sets, aprobación de corpus,
IP, releases, ciclo de vida de modelos, sync edge, heartbeats de nodos y autorizaciones explícitas de
`/hydra/v1/goals` (sin token configurado, solo loopback). El Studio tiene un campo para él (se guarda solo
en la pestaña).
Imagen de sandbox endurecida: `docker build -t hydra-sandbox:py312-v3 -f infra/sandbox/Dockerfile .`
Detalle en [docs/architecture.md](docs/architecture.md) y [docs/INTEGRATION_PLAN.md](docs/INTEGRATION_PLAN.md).

## Despliegue

* **DEV**: `docker compose up -d` (gateway, worker del fabric, Model Factory, PostgreSQL, Redis, Ollama, sandbox);
  `--profile gpu` añade vLLM, `--profile nats` NATS JetStream y `--profile observability` Prometheus + Grafana.
* **CLUSTER**: `infra/kubernetes/` (plano de control/datos, GPUs vía device plugin o DRA) y `infra/terraform/`.
* **EDGE**: una máquina, Ollama/llama.cpp, políticas offline y `hydra sync export|import` firmado.
* PostgreSQL (`sql/schema.sql`) persiste hoy tareas, eventos, ejecuciones de inferencia, métricas de
  modelos, memoria, la cola del Execution Fabric (`fabric_*`, compartida por todos los nodos con
  `FOR UPDATE SKIP LOCKED`), el ledger firmado (`ip_events`/`ledger_anchors`: una sola cadena para todos
  los nodos, con triggers que impiden UPDATE/DELETE/TRUNCATE) y los logs del corpus (`hydra_logs`: registros,
  linaje, tombstones y snapshots), del World Model (deltas y snapshots), del registro de invenciones y de
  los manifiestos de artefactos (`hydra_logs`); cada nodo reproduce los logs en el mismo orden total.
  También el outbox de captura (`capture_outbox`: cada nodo reclama lo que reintenta, sin duplicados).
  Requiere el extra `postgres`. Los blobs de artefactos van a `HYDRA_ARTIFACT_OBJECTS`: un volumen
  compartido o un bucket S3/MinIO (extra `s3`); los objetos locales existentes se copian una vez al cambiar.
  También el estado de la línea runtime (cadenas, evidencia, despliegues, outbox, métricas, trazas) y los
  registros pequeños del motor y la fábrica (`hydra_documents`: flags, config sets, secretos, lab,
  glosarios, ciclo de vida, registro de la factoría, memoria de fallos, aprendizaje del planificador).
* **Varias réplicas** (`infra/kubernetes/`): `hydra-api` ×2 y `hydra-fabric-worker` ×2 sobre PostgreSQL,
  `/data` en un volumen ReadWriteMany (solo ficheros de nombre único: blobs, vuelos, releases, builds) y las
  claves en el Secret `hydra-keys` (`hydra keys export --out <dir>`). `HYDRA_REQUIRE_SHARED_STATE=true`
  hace que un pod con algún plano en ficheros locales se niegue a arrancar.

## Pruebas

```bash
ruff check . && pytest                   # lint + unitarias + extremo a extremo offline (ambas líneas)
set HYDRA_IT_POSTGRES=postgresql://hydra:hydra@localhost:5432/hydra
set HYDRA_IT_REDIS=redis://localhost:6379/0
set HYDRA_IT_NATS=nats://localhost:4222
```

## Límites conocidos

* Conversión/cuantización GGUF, AWQ/GPTQ/FP8, MLX, ONNX y entrenamiento LoRA/DPO dependen de
  herramientas externas (llama.cpp, llm-compressor, mlx-lm, optimum, torch/transformers/peft/trl) que
  HYDRA integra pero no incluye; sin ellas lo informa (`ToolMissing`) en vez de fingir.
* El scheduler de clúster y la analítica federada están probados en una máquina y con nodos simulados;
  el estado compartido entre réplicas está probado con varios nodos concurrentes contra PostgreSQL real.
  Los experimentos del lab miden sus brazos en el nodo que sirve el tráfico.
* En Ollama el tipo de caché KV es un ajuste del servidor (`OLLAMA_KV_CACHE_TYPE`): el AutoBuilder
  lo varía solo con llama-server.
* HYDRA registra evidencia técnica y de autoría; no decide patentabilidad ni autoría legal.

Documentación: [docs/architecture.md](docs/architecture.md), [docs/adr/](docs/adr/),
[docs/security.md](docs/security.md), [docs/ip-process.md](docs/ip-process.md), [docs/runtime/](docs/runtime/).

## Calibrador independiente de Hyd

El módulo `hyd_calibrator` funciona con Python 3.12 y NumPy sin arrancar HYDRA. [Preparación, entrenamiento y calibración](docs/CALIBRATOR.md). La instalación del repositorio también incluye el comando `hyd-calibrator`; no activa modelos automáticamente.
