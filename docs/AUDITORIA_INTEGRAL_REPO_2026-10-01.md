<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Auditoría integral del repositorio HYDRA — 2026-10-01

Rama auditada: `integration/hydra-1.0` (HEAD `33ea0a7`) + cambios locales sin commitear
(`hydra/model_factory/train_lora.py`, `hydra/model_factory/build_hydra.py`, programa de
adestramento v1 sin trackear). Alcance: 848 ficheros versionados, ~49 800 líneas Python,
infraestructura (Docker, Compose, Kubernetes, Terraform), SQL, CI, SDKs, UI, configuración y
documentación.

## 0. Resumen ejecutivo

| Severidad | Nº | Lo más importante |
|---|---|---|
| **Crítico** | 4 | Los manifiestos k8s no arrancan; `sync/import` acepta las claves de confianza que envía el cliente; el WebSocket no tiene autenticación sin API key; el contexto Docker incluye `models/` (75 GB) y `data/keys` + `data/secrets` |
| **Alto** | 11 | `/goals` permite autoautorizarse; el endpoint de modelos hashea 75 GB por petición; los workers instalados no encuentran `sql/schema.sql`; 10 tablas SQL sin código; la cola del fabric en SQLite sobre RWX con 7 réplicas; evaluación humana rota fuera del checkout |
| **Medio** | 22 | Dos "líneas" duplicadas (≈50 clases repetidas); traversal de `config/{env}` en Windows; claves privadas en claro junto a los datos; escrituras de estado no atómicas; dashboards Grafana sin provisionar y con una métrica mal construida |
| **Bajo** | 25+ | Código muerto, configs y recetas obsoletas, documentación desactualizada, deriva de versiones, higiene |

Estado base, verificado:

* `ruff check .` (reglas del proyecto `E4,E7,E9,F`): **limpio**.
* `pytest`: **599 passed, 5 skipped en 16 min 32 s**. Casi todo ese tiempo se va en **un solo test**
  (ver H-02). `kev_tests/` no se ejecuta nunca (está fuera de `testpaths`).
* Ruff ampliado (`B,S,PL,RUF,SIM,UP,ARG…`): 2 879 avisos; tras el triage quedan 83 relevantes
  fuera de los tests (ver §9).
* No hay secretos reales versionados: los patrones `sk-…`, `ghp_…` y `AKIA…` son fixtures de
  red-team y de tests. `.env` está ignorado.

Durante la auditoría no se ejecutaron `docker build`, `docker compose up`, `kubectl apply` ni
`terraform plan`, así que esos hallazgos llevan la etiqueta *(estático)*. En la fase de corrección sí se
construyó y arrancó la imagen y se validaron Compose, kubeconform y Terraform (ver §14).

---

## 1. Seguridad

### C-01 · Crítico · `sync/import` confía en las claves que envía el cliente
`hydra/api/platform_routes.py:915-919`
```python
keys = set(body.trusted_keys) or {runtime.signer.public_pem}
return import_delta(runtime, SyncBundle.model_validate(body.bundle), keys)
```
Quien llama manda el bundle **y** la clave pública con la que se verifica. Basta con firmar un
bundle con una clave propia y enviarla en `trusted_keys` para inyectar deltas del World Model y
registros de corpus (incluidos estados `training_status` elevados) en el nodo. La firma Ed25519
deja de proteger nada.
**Corrección:** quitar `trusted_keys` del cuerpo. Las claves de confianza deben venir de
configuración del servidor (`data/keys/trusted/*.pub.pem` o `HYDRA_SYNC_TRUSTED_KEYS`). Exigir
token admin para esta ruta.

### C-02 · Crítico · WebSocket `/v1/ws/tasks` sin autenticación cuando no hay API key
`hydra/api/platform_routes.py:274-280`
```python
if key and token != key:   # sin key -> acepta a cualquiera
```
Las rutas HTTP, cuando falta `HYDRA_API_KEY`, solo aceptan loopback (`main.py:auth`). El WS no
aplica esa regla, así que con `hydra serve --host 0.0.0.0` y sin clave cualquier cliente remoto
ejecuta tareas. Además:
* la comparación no es de tiempo constante (`!=` en vez de `secrets.compare_digest`);
* acepta la clave por query string (`?api_key=`), que acaba en logs y proxies. El SDK TS la manda
  así: `sdk/typescript/src/index.ts:74`;
* se salta el rate limit y la comprobación de tenant que sí hace `_run_task`.

**Corrección:** reutilizar la misma dependencia `auth` + `throttle` (o una equivalente para WS),
tratar el caso sin key como loopback-only, usar `compare_digest` y aceptar el token solo en una
cabecera o en el subprotocolo.

### H-01 · Alto · `/hydra/v1/goals`: el cliente se autoautoriza acciones de riesgo
`platform_routes.py:262` pasa `authorized=set(body.authorized)` y `planning/runner.py:253` llama a
`gate.check(..., authorized, verified=True)`. En `governance/security.py:203-210` las acciones
`VERIFY` se permiten porque `verified=True` está fijo, y las `DENY`/explícitas se permiten si la
capacidad aparece en `authorized`, una lista que escribe el propio cliente. La "autorización humana
explícita" queda en una casilla que marca quien llama.
**Corrección:** que `authorized` salga de una aprobación persistida (ID de aprobación firmado o
emitido por un endpoint admin) y no del cuerpo de la petición. Quitar `verified=True` fijo.

### M-01 · Medio · API de plataforma sin separación de privilegios
Una sola `HYDRA_API_KEY` permite: aprobar corpus para entrenamiento (`/corpus/records/{id}/review`,
con un `reviewer` libre que se puede suplantar), confirmar creencias como `by=human`
(`/world/beliefs/{id}/confirm`), cambiar feature flags y config sets, lanzar red-team, exportar e
importar sync, construir releases y firmar invenciones. La línea runtime sí separa
`HYDRA_ADMIN_TOKEN`. El modelo `Principal`/capabilities de `governance/security.py` existe pero la
API no lo usa.
**Corrección:** aplicar `require_admin_access` (o roles `Principal`) a todas las rutas que
escriben gobierno, IP, corpus o configuración. Derivar `reviewer`/`actor` de la identidad
autenticada, no del cuerpo.

### M-02 · Medio · Path traversal en `/hydra/v1/config/{env}` (Windows)
`governance/config_registry.py:45-46` construye `self.root / f"{env}.jsonl"` sin validar nada. En
Windows `env="..\\..\\x"` (codificado como `%5C`) escribe fuera de `data/configs`. La máquina de
producción es Windows. **Corrección:** `safe_id(env)` (ya existe en `core/paths.py:30`) o una lista
blanca `dev|lab|staging|canary|production`. Revisar lo mismo en `flags/{name}` y
`glossaries/{name}`.

### M-03 · Medio · Claves privadas en claro junto a los datos que protegen
* `ledger/signing.py:34-49`: la clave Ed25519 del ledger se guarda en PEM `NoEncryption` en
  `data/keys/`. Quien puede reescribir `data/ledger` puede volver a firmarlo.
* `governance/secrets.py:38-45` (`.broker.key`) y `ledger/ip.py:452-471` (vault de secretos
  empresariales): la clave Fernet está en el mismo directorio que el texto cifrado.
* `os.chmod(…, 0o600)` no tiene efecto en Windows.

**Corrección:** cargar las claves desde el keyring del SO, DPAPI, un KMS o una variable de entorno
o fichero montado fuera de `HYDRA_DATA_DIR`. Documentar que hoy el cifrado en reposo solo protege
frente a una fuga del directorio de datos sin la clave.

### M-04 · Medio · Studio: API key y conversación en `localStorage`, sin CSP
`api/studio.html:150-152,200`: guarda `hydra_key` y los últimos 100 mensajes en `localStorage`. No
hay cabecera `Content-Security-Policy`. `esc()` (`studio.html:155`) solo escapa `& < >` y no las
comillas; hoy solo se usa en contenido de texto, pero cualquier uso en atributos abriría un XSS.
**Corrección:** CSP estricta en `/studio`, `sessionStorage` o un token de sesión corto, y añadir
`"` y `'` a `esc`.

### M-05 · Medio · Evidencias de canary/shadow declaradas por quien llama
`runtime/api.py` (`/admin/deployments/{id}/shadow|canary`) recibe `agreement_rate`, `error_rate` y
`p95_latency_ms` en el cuerpo, y el gate de promoción decide con esos números. Aunque exige token
admin, la promoción no se basa en métricas medidas por el sistema (`operating_metrics`,
`runtime_health`). **Corrección:** calcular la evidencia en el servidor a partir de lo que
registran `RuntimeEvidenceStore` y `OperatingMetricsStore`.

### B-01 · Bajo · Otros
* `/metrics` y `/health` no tienen autenticación. Es aceptable para Prometheus, pero exponen
  contadores de corpus, ledger y modelos. Mejor restringirlos por red o servirlos en un puerto
  interno.
* `/hydra/v1/evaluation/review` (HTML) y `/studio` no tienen autenticación. Solo sirven HTML
  estático; los datos sí piden key.
* `core/config.py:41` `internal_api_key = "internal"`: un valor por defecto que parece un secreto.
  Mejor vacío.
* Rate limiter en memoria por proceso: con 4 réplicas el límite real es ×4.

---

## 2. Despliegue e infraestructura

### C-03 · Crítico · Los manifiestos Kubernetes no arrancan *(estático)*
`infra/kubernetes/10-control-plane.yaml:17` y `20-data-plane.yaml:15,32` usan
`args: ["serve", …]`, `["worker", …]` y `["factory", "worker"]`. El `Dockerfile` no define
`ENTRYPOINT`, solo `CMD ["uvicorn", …]`. En k8s, `args` sustituye a `CMD`, así que el contenedor
intentaría ejecutar un binario llamado `serve` o `worker` y fallaría con `exec: not found`.
**Corrección:** `command: ["hydra"]` + `args: [...]`, o `ENTRYPOINT ["hydra"]` en la imagen (en ese
caso Compose debe dejar de anteponer `hydra`).

Otros fallos k8s:
* **Secret con credenciales `change-me`** versionado (`00-namespace.yaml`) y contraseña de
  Postgres en claro en `40-infra.yaml`.
* `HYDRA_SANDBOX_BACKEND: docker` sin Docker en los pods: el sandbox no funciona en el perfil
  CLUSTER.
* ~~Las probes deberían usar `/ready`~~ **(corregido al implementar):** `/ready` también exige el
  llama-server de la línea runtime (`HYDRA_LLM_URL`), que el perfil k8s no despliega, así que con
  `/ready` el pod no llegaría nunca a estar listo (comprobado en contenedor: `llm_unhealthy`). Se
  mantiene `/health` y el manifiesto lo explica.
* `hydra-api` ×4 réplicas + `fabric-worker` ×3 + `factory` ×1 montan **el mismo PVC RWX** en el
  que viven SQLite (`fabric`, `capture_outbox.db`), JSON de estado y el ledger de ficheros. SQLite
  sobre NFS/RWX con escritores concurrentes se corrompe y los JSON se pisan (ver H-06/M-08).
* `/app/runtime` (estado de la línea runtime: `hydra.db`, `deployments.json`) no tiene volumen y
  se pierde en cada reinicio.
* No hay `securityContext` (runAsNonRoot, readOnlyRootFilesystem, drop ALL), `NetworkPolicy`,
  límites en workers ni PDB/HPA.
* Imágenes sin digest (`vllm/vllm-openai:latest`, `postgres:17`, `nats:2.11`, `redis:8`),
  mientras que Compose sí las fija.
* `HYDRA_OTEL_ENDPOINT` apunta a `otel-collector.observability.svc`, que no está definido.
* `vllm-reasoner` no tiene `HF_TOKEN` ni volumen de caché.
* Nadie aplica `sql/schema.sql`: no hay Job ni initContainer de migración (ver E).

### C-04 · Crítico · `.dockerignore` envía 75 GB y secretos al daemon *(estático)*
`.dockerignore` solo excluye `__pycache__`, `.venv`, `.env`, `.git`, `workspace/` y `tests/`.
Quedan dentro del contexto de build `models/` (**75 GB** de GGUF), `data/` (incluye
**`data/keys`** y **`data/secrets`**), `runtime/`, `build/`, `dist/`, `docs/evidence`,
`.ruff_cache` y `.pytest_cache`. Ningún `COPY` los mete en la imagen, pero se transfieren al daemon
(que puede ser remoto vía `DOCKER_HOST`) y cada build tarda muchísimo más.
**Corrección:** pasar a lista blanca (`*` y luego
`!hydra !config !sql !pyproject.toml !README.md !LICENSE !NOTICE`).

### H-02 · Alto · `GET /hydra/v1/models/artifacts` (y `/v1/models` del runtime) hashea todos los GGUF en cada petición
`runtime/api.py:259-262` → `runtime/model_scout.py:101-112` → `_sha256(resolved)` de cada `*.gguf`
bajo `models/`, sin caché, **de forma síncrona dentro de un endpoint `async`**. Con 75 GB locales:
* bloquea el event loop del gateway entero durante minutos. Cualquier otra petición (incluido
  `/health`) se queda esperando;
* explica los 16 minutos de la suite: `tests/runtime/test_api.py::test_models_endpoint_is_local_inventory`
  hashea el `models/` real del checkout. El test no es hermético.

**Corrección:** cachear el hash por `(path, size, mtime)` en `runtime/hydra.db`, hacer el escaneo
con `asyncio.to_thread`, permitir `?hash=false` y, en el test, apuntar
`settings.models_dir` a `tmp_path`.

### H-03 · Alto · Workers instalados no encuentran `sql/schema.sql` *(estático, alta probabilidad)*
`persistence/postgres.py:14` usa `SCHEMA = ROOT / "sql" / "schema.sql"`. `core/config.py:14-18`
resuelve `ROOT` así: checkout de fuentes → `share/hydra` instalado → `cwd`. Dentro de la imagen:
* `uvicorn` importa `hydra` desde `/app` (cwd), así que `ROOT=/app` y existe `/app/sql`;
* `hydra worker` y `hydra factory worker` (servicios de Compose) se lanzan con el console script.
  `hydra` sale de `site-packages`, `ROOT=/usr/local/share/hydra` (que tiene `config/` pero **no**
  `sql/`), y con `HYDRA_POSTGRES_URL` puesto `create_pool()` lanza `FileNotFoundError`.

**Corrección:** instalar el esquema en `share/hydra/sql` (data-files) y copiarlo antes del
`pip install` en la imagen.

### H-04 · Alto · Python distinto en imagen y en CI
`Dockerfile` usa `python:3.14-slim`; `pyproject` (`target-version py312`), CI (`3.12`), el venv
local (3.12.10) y la imagen sandbox (`3.12-slim`) usan 3.12. La imagen de producción usa un
intérprete que ningún test ha ejecutado. **Corrección:** fijar `python:3.12-slim@sha256:…`, o
añadir 3.14 a la matriz de CI. El `docker:29-cli` del Dockerfile tampoco va fijado por digest.

### M-06 · Medio · Docker Compose
* El comentario dice "Only hydra-api publishes a port", pero `prometheus` (9090) y `grafana`
  (3000, con credenciales por defecto `admin/admin`) también publican puertos.
* `hydra-worker` y `hydra-factory` no montan `hydra_runtime`, y `hydra-worker` tampoco `models`.
* `ollama`, `vllm-*`, `worker` y `factory` están en la red `public` (con salida a Internet). Es
  necesario para descargar pesos, pero conviene documentarlo o separar la descarga.
* `sandbox-controller` con `IMAGES: 1` + `POST: 1` permite `docker pull` y `build` de imágenes
  arbitrarias. Mejor limitarlo a crear y arrancar.

### M-07 · Medio · Terraform *(estático)*
`infra/terraform/main.tf` aplica todos los YAML con `kubernetes_manifest` y `for_each`, sin orden:
el `Namespace` y los recursos con namespace se crean en paralelo, y en el primer `apply` falla.
`kubernetes_manifest` también necesita que la API (incluido `resource.k8s.io/v1`, k8s ≥1.34)
exista en tiempo de plan. El Secret acaba en el state en claro. **Corrección:** separar el
Namespace con `depends_on`, sacar secretos a `kubernetes_secret` con valores de variables
sensibles, o usar Kustomize/Helm.

### B-02 · Bajo · Imagen sandbox desalineada
`infra/sandbox/Dockerfile` instala `pytest>=8,<9` y `pytest-asyncio<1`, mientras que el proyecto
exige `pytest>=9.0.3` y `pytest-asyncio>=1.4`. El verificador de código ejecuta tests con
versiones distintas a las de CI. Además no está fijado por digest.

---

## 3. Corrección (bugs de comportamiento)

| ID | Sev. | Ubicación | Problema | Corrección |
|---|---|---|---|---|
| H-05 | Alto | `api/evaluation_routes.py:15-18,49` + `pyproject.toml:51` | `ROOT=parents[2]` apunta fuera del paquete instalado; `data/external-evaluation-v2` no está versionado (`data/` ignorado); `evaluation_review.html` **no está en `package-data`**. En wheel o Docker, `/hydra/v1/evaluation/*` devuelve 500; en un clon limpio, `/cases` también | Datos de evaluación en un directorio configurable (`settings.data_dir`), HTML a `package-data`, 404/409 claros si falta el dataset |
| M-09 | Medio | `api/platform_routes.py:322` | `/v1/responses` no captura `HydraTaskFailed`: el fallo de un modelo devuelve 500 en lugar de 502/503 como `/v1/hydra` y `/v1/chat/completions` | Mismo manejo de errores que el resto |
| M-10 | Medio | `api/platform_routes.py:210-221` | `_spawn` crea la tarea sin guardar referencia (`loop.create_task(run())`): asyncio puede recogerla con el GC a mitad de ejecución (aviso de la documentación oficial). `jobs` crece sin límite | Guardar la referencia en un set con `add_done_callback(discard)` y aplicar TTL/LRU a `jobs` |
| M-11 | Medio | `observability/tracing.py:118` | Misma situación con `create_task(self._export(batch))` (export OTLP) | Igual |
| M-12 | Medio | `observability/tracing.py:202` + `:33` | `hydra_confidence_pct` (0–100) se observa con `BUCKETS_MS` (50…120 000 ms): todo cae en los dos primeros buckets y el p50 de Grafana no significa nada | Buckets propios (`10,20,…,100`) por histograma |
| M-13 | Medio | `runtime/config.py` | La línea runtime lee `os.getenv` **en tiempo de import** y **no lee `.env`**, al contrario que `core/config.Settings` (`env_file=".env"`). Un `HYDRA_ADMIN_TOKEN` puesto en `.env` funciona en la plataforma pero no en las rutas admin del runtime (503) cuando se lanza con `hydra serve` fuera de Compose | Unificar en un único `Settings` de pydantic (ver F) |
| M-14 | Medio | `runtime/api.py:56-121` | Más de 30 singletons creados **al importar el módulo** (SQLite `runtime/hydra.db` relativo al **cwd**, ficheros de despliegue, worker). Importar `hydra.api.main` ya crea `./runtime/` en el directorio desde el que se ejecute. Es la razón del hack "mounted once per process" de `runtime_routes.py` | Fábrica `create_runtime_app(settings)` con estado en `app.state` y rutas basadas en `data_dir` |
| M-15 | Medio | `hydra/training/finetuning_v8.py:46` | Importa `scripts.evaluate_external_holdout`. `scripts/` no forma parte del wheel, así que en instalación da `ModuleNotFoundError` | Mover `matching_json` a `hydra/training/` |
| B-03 | Bajo | `api/main.py:auth` vs `runtime/security.py` | Dos implementaciones de auth: la de plataforma considera `localhost/testclient/is_loopback`; la de runtime, una lista fija (`127.0.0.1, ::1, …`) que no cubre `::ffff:127.0.0.1` ni `127.0.0.2` | Una sola función |
| B-04 | Bajo | `/v1/chat/completions`, `/v1/responses` | `usage` siempre a 0 (los tokens reales están en el tracer) | Rellenarlo desde `meta` |
| B-05 | Bajo | `/v1/responses` | Un `model` desconocido cae en silencio en `balanced`; `/v1/chat/completions` devuelve 400 | Mismo criterio |
| B-06 | Bajo | `training/verified_corpus.py:61`, `regression_corpus.py:55` | Validación con `assert` (desaparece con `python -O`) y `exec` de plantillas | `if …: raise ValueError` |
| B-07 | Bajo | `evals/e2e.py:75` | `eval(f"{a}{op}{b}")`: es seguro (enteros generados), pero innecesario | `operator.add/sub/mul` |
| B-08 | Bajo | `model_factory/train_lora.py` (cambio sin commitear) | `warmup_steps` se calcula sobre `len(data)` y `job["epochs"]` aunque haya `max_steps`; conviene un test que fije el valor esperado | Test unitario de la fórmula |

---

## 4. Rutas HTTP: duplicadas, sombreadas, incoherentes y no conectadas

142 rutas en 6 módulos (`main.py`, `os_routes.py`, `platform_routes.py`, `web_routes.py`,
`evaluation_routes.py` y `runtime/api.py`, montado por `runtime_routes.py`). Todas las rutas que
consumen Studio, el SDK Python y el SDK TS **existen**. No hay llamadas rotas desde los clientes.

### 4.1 Sombreadas (código del runtime que nunca se sirve en el gateway)
`runtime_routes.register_runtime_routes` descarta las rutas del runtime que chocan con las de la
plataforma:

| Ruta | Gana | Queda muerta en el gateway |
|---|---|---|
| `GET /health` | `main.py:109` | `runtime/api.py:176` |
| `POST /v1/translate` | `platform_routes.py:835` | `runtime/api.py:227` + `runtime/translation.py` (`TranslationService`, `GlossaryStore`) |
| `PUT /v1/glossaries/{}` | `platform_routes.py:853` | `runtime/api.py:244` |
| `GET /v1/models` | `main.py:213` | se reubica en `/hydra/v1/models/artifacts` |

Solo se usan en el modo standalone (`scripts/run_api.sh`). **Recomendación:** quitar el modo
standalone o declararlo como obsoleto y borrar el traductor y el glosario duplicados del runtime.

### 4.2 Funcionalidad duplicada bajo prefijos distintos (`/v1`, `/hydra/v1`, `/v1/os`)
| Función | Rutas |
|---|---|
| Ejecutar una tarea / chat | `POST /v1/hydra`, `/v1/hydra/stream`, `/v1/tasks`, `/hydra/v1/tasks` (**idénticas**, `platform_routes.py:243-249`), `/v1/chat` (runtime), `/hydra/v1/tasks/execute` (runtime), `/v1/chat/completions`, `/v1/responses`, WS `/v1/ws/tasks` → **9 puertas de entrada** con validaciones, errores y límites distintos |
| Replay | `GET /v1/tasks/{id}/replay`, `POST /hydra/v1/tasks/{id}/replay`, `GET /hydra/v1/admin/replay/{id}/audit` |
| Catálogo de modelos | `/v1/models`, `/hydra/v1/models/catalog`, `/hydra/v1/models/artifacts`, `/v1/factory/variants`, `/hydra/v1/models/graph` |
| Política | `GET /v1/policy`, `POST /v1/policy/classify`, `GET /hydra/v1/policy/rules`, `POST /hydra/v1/policy/evaluate` |
| Evals | `POST /v1/evals/run`, `POST /hydra/v1/evals/e2e` |
| Lab | `/v1/lab/experiments*`, `/hydra/v1/lab/improvements` |
| Grafos | `/v1/memory/graph`, `/hydra/v1/world/graph` |
| Estado | `/v1/os/status`, `/hydra/v1/system/invariants`, `/hydra/v1/system/dod`, `/ready`, `/health` |
| Métricas | `/metrics`, `/v1/metrics/models`, `/hydra/v1/admin/metrics`, `/hydra/v1/observability` |

Además, el reparto entre `main.py`, `os_routes.py` y `platform_routes.py` no sigue dominios: hay
tareas en los tres, y modelos y políticas en dos. **Recomendación:** fijar `/hydra/v1` como API nativa versionada y dejar
`/v1/*` solo para la compatibilidad OpenAI (`/v1/chat/completions`, `/v1/responses`,
`/v1/embeddings`, `/v1/models`). Marcar el resto con `deprecated=True` y
`Deprecation`/`Sunset`, y reorganizar en `APIRouter` por dominio en lugar de funciones
`register_*` con 900 líneas.

### 4.3 Rutas sin consumidor en Studio ni en los SDK
`/v1/cluster/place`, `/v1/cluster/heartbeat`, `/v1/fabric/work*`, `/hydra/v1/edge/autobuild`,
`/edge/residency`, `/edge/sync/*`, `/hydra/v1/federated/analytics`, `/hydra/v1/licenses/evaluate`,
`/hydra/v1/releases/gate`, `/releases/{name}/verify`, `/hydra/v1/ip/inventions/{inv}/*`,
`/hydra/v1/capture/outbox`, `/hydra/v1/secrets`, `/hydra/v1/config/*`,
`/hydra/v1/models/{id}/discover|lifecycle`, `/hydra/v1/models/graph`, `/hydra/v1/jobs/{id}`
(Studio lanza jobs pero no hace polling), `/v1/memory/*`, `/v1/tasks/{id}/claims|artifacts|provenance`,
`/v1/factory/jobs*`. No es un error, pero son superficie expuesta sin UI ni tests E2E de cliente.
Conviene comprobar cuáles son necesarias.

### 4.4 Paridad de SDKs
El SDK TS cubre 8 operaciones y el Python 10. Ninguno cubre IP, releases, training, cluster ni
fabric. El SDK TS no se compila ni se prueba en CI y no tiene lockfile.

---

## 5. Base de datos: tablas sin uso y tablas que faltan

### H-07 · Alto · 10 tablas de `sql/schema.sql` sin ninguna línea de código que las use
`ip_events` (con el trigger de inmutabilidad que cita el README), `ledger_anchors`, `inventions`,
`artifacts`, `corpus_records`, `corpus_lineage`, `world_entities`, `world_relations`, `beliefs` y
`world_deltas` no se leen ni se escriben desde ninguna parte. Ledger, corpus, World Model,
artefactos e invenciones viven **solo** en ficheros bajo `data/`. El README ("Esquema PostgreSQL
multi-nodo… ledger con triggers que impiden UPDATE/DELETE") y `ledger/chain.py:11` describen una
persistencia que no existe. **Decisión necesaria:** implementar los repositorios Postgres de esos
planos (necesario para el perfil CLUSTER con varias réplicas) o borrar las tablas y corregir la
documentación.

Tablas que sí se usan: `tasks`, `events`, `inference_runs`, `model_metrics`
(`persistence/postgres.py`) y `memories` (`memory/store.py`).

### H-06 · Alto · Tablas que faltan en Postgres (hoy solo en SQLite local)
| Tabla (SQLite) | Fichero | Problema multi-nodo |
|---|---|---|
| `work`, `idempotency`, `checkpoints` | `cluster/fabric.py:67-71` | La cola del Execution Fabric (leases, reintentos, dead-letter) es un SQLite en `data/`. Con 7 réplicas sobre RWX (k8s), o sin volumen compartido, no hay cola distribuida, aunque el README la presenta así |
| `outbox`, `task_commits` | `runtime/outbox.py:47`, `runtime/capture_uow.py:35` | Outbox transaccional por nodo |
| `deployment_evidence`, `runtime_health`, `operating_metrics` | `runtime/*_store.py` | Estado de despliegue por nodo y efímero en k8s |
| capture outbox | `core/capture_outbox.py` → `data/capture_outbox.db` | Idem |
| market cache | `market.py` | Idem |

Faltan además: índices por `status, priority, available_at` si la cola pasa a Postgres, migraciones
versionadas (hoy son `ALTER TABLE … IF NOT EXISTS` sueltos en `schema.sql`) y un Job o
initContainer que las aplique. **Corrección:** introducir migraciones (Alembic o SQL numerado),
portar fabric/outbox a Postgres (`SELECT … FOR UPDATE SKIP LOCKED`) cuando haya
`HYDRA_POSTGRES_URL` y mantener SQLite solo en EDGE.

---

## 6. Duplicación de código: dos plataformas dentro de un paquete

`hydra/runtime/` (96 módulos, "línea HYDRA-SO") vuelve a implementar casi todos los subsistemas de
la plataforma `hydra/*`. **50 nombres de clase aparecen en dos o tres módulos distintos**, entre
ellos:

| Concepto | Plataforma | Runtime |
|---|---|---|
| Settings | `core/config.py` (pydantic, `.env`) | `runtime/config.py` (dataclass + `os.getenv`) |
| Kernel | `core/kernel.HydraKernel` | `runtime/kernel.HydraKernel` |
| Contratos | `core/task.HydraTask/HydraResult/TaskStatus`, `core/contracts.TaskType` | `runtime/contracts.*` |
| Registry | `registry/registry.ModelRegistry`, `ModelProfile` | `runtime/model_registry.*` |
| Planner | `scheduler/planner.Planner`, `ExecutionPlan` | `runtime/planner.*` (+ `planning/goals.ExecutionPlan`: 3 versiones) |
| Verifier | `verification/verifier.Verifier` | `runtime/verifier.Verifier` |
| Sandbox | `tools/sandbox.py` | `runtime/sandbox.py` |
| Tools / workspace | `tools/registry`, `tools/workspace.WorkspaceManager` | `runtime/tools`, `runtime/workspaces` |
| Corpus / datasets | `corpus/store`, `corpus/factory.DatasetFactory` | `runtime/corpus`, `runtime/dataset_factory` |
| Artefactos | `artifacts/store.ArtifactStore` | `runtime/artifacts.ArtifactStore` |
| Provenance / hash-chain | `provenance/engine`, `ledger/chain` | `runtime/provenance`, `runtime/hash_chain` |
| Policy | `governance/policy_dsl.PolicyEngine`, `policy/kernel` | `runtime/policy.PolicyEngine` |
| Traducción | `edge/translation` | `runtime/translation` (sombreado, §4.1) |
| Budgets | `core/budget.BudgetExceeded` | `runtime/budgets.BudgetExceeded` (`platform_routes.py:24` importa **el del runtime**) |
| Model factory | `model_factory/*`, `training/autoquant` | `runtime/model_factory`, `runtime/autoquant`, `runtime/gguf`, `runtime/llama_factory` |
| Observabilidad | `observability/tracing.CognitiveTracer` | `runtime/observability.CognitiveTracer` |
| Creencias | `world/model.Belief` | `runtime/beliefs.Belief` (+ `blackboard/state.Belief`) |

También hay duplicados **dentro de la plataforma**:
* `CognitiveBudget` en `core/budget.py:13` **y** `core/task.py:21`, con campos distintos
  (`max_parallel_workers` frente a `max_parallelism`);
* `WorldEvent`/`WorldRelation` en `world/model.py` **y** `world/state.py`;
* `HardwareProfile` en `edge/profiles.py` **y** `model_factory/hardware.py`;
* `SimulationResult` en `planning/simulator.py` **y** `simulation/engine.py`;
* `Procedure` en `memory/models.py` **y** `planning/procedures.py`;
* helpers con cuerpo idéntico: `_print`/`_kv` (`cli.py` y `cli_platform.py`), `_cos`
  (`corpus/dedup.py:138` y `world/knowledge.py:83`), `_now` ×3, `count_tokens`/`_tokens`, `_obj`,
  `sha256_file` ×2 + `file_sha256` + `_sha256` + `sha256` (5 funciones de hash de fichero).

Ya hay consolidación en marcha: `runtime/{circuit_breaker,hardware,language,rate_limit}.py` son
reexportaciones. **Plan:** seguir ese patrón módulo a módulo. Por cada par, elegir la
implementación con más tests, convertir la otra en reexportación, migrar los imports y borrar la
reexportación en la siguiente versión. Orden sugerido: `Settings` → contratos/`BudgetExceeded` →
hash/IO helpers → traducción → artefactos/provenance → sandbox/workspace → verifier → planner →
kernel.

---

## 7. Código muerto y obsoleto

### 7.1 Módulos que no importa ningún código de producción
* **Sin ningún uso** (ni producción, ni tests, ni scripts): `training/hybrid_classifier.py` (sin
  `__main__`): **borrar**.
* **Solo con `__main__`, sin referencias en docs**: `training/evaluate_decision.py`,
  `evaluate_human_paraphrases.py`, `evaluate_kev_candidate.py`, `human_dev_v2.py`,
  `validate_kev_candidate_stability.py`, `validate_kev_control.py`; `model_factory/export_ollama.py`.
* **Solo los usan sus tests** (funcionalidad sin conectar en el runtime):
  `runtime/{autoquant, benchmark_protocol, build_supervisor, coding_loop, dataset_factory,
  deployment_resolver, physical_registry, quality_eval, replay_runtime, static_analysis,
  tool_audit, variant_runner}.py`, `planning/epistemic.py` (la "ganancia de información" del
  README no se usa en el planner) y `model_factory/deploy_bridge.py`.

Recomendación: conectar lo que forme parte de la hoja de ruta (`coding_loop`, `static_analysis`,
`quality_eval` y `epistemic` tienen pinta de serlo) y mover el resto a `hydra/experimental/` o
borrarlo.

### 7.2 `hydra/training/` (50 módulos): scripts históricos dentro del paquete
`instruction_corpus_v2/v4/v5/v6`, `human_dev_v1/v2`, `train_decision_v2/v4`,
`decision_corpus_v3`, `evaluate_instruction_v2`, `finetuning_v8`, `prepare_kev_hydra_v2`…
generan artefactos de iteraciones ya cerradas. Se distribuyen en el wheel, aumentan la superficie y
duplican estructura (12 funciones `build()`, 10 `evaluate()`, 9 `validate()`). **Recomendación:**
dejar en `hydra/training` solo la librería (lab, program, calibration, signing, evidence_io,
corpus_integrity, métricas) y mover los generadores versionados a `research/` o `experiments/`
fuera del paquete, con un README que enlace cada uno con su evidencia en `docs/evidence`.

### 7.3 `scripts/` (41 ficheros)
29 scripts no tienen ninguna referencia en código ni en documentación (fuera de `docs/evidence`):
`audit_*`, `evaluate_external_holdout`, `train_*_when_free`, `serve_kev_candidate`,
`query_kev_hydra_candidate`, `run_studio_candidate`/`run_studio_validated`, `validate_*`,
`build_gguf.sh`, `repair_web_pilot_encoding.py`, etc. Ninguno tiene test de humo. **Acción:**
inventario en `scripts/README.md` (propósito, estado activo/obsoleto, evidencia producida) y
archivar los obsoletos.

### 7.4 Configuración y recetas obsoletas
Sin ninguna referencia en código ni en docs:
* ~~`config/models.hydra-instruction-v2…v8.yaml` sin referencias~~ **(corregido al implementar):** sí
  se usan, mediante f-strings (`scripts/query_kev_hydra_candidate.py` construye
  `config/models.hydra-instruction-v{version}.yaml`). No se borran. Son 7 ficheros casi idénticos que
  se podrían generar desde una plantilla, pero es una mejora opcional.
* Recetas `config/recipes/hydra-instruction-v3/v5/v6.json`, `v9-four-high/four-low/seven-low.json` y
  `hydra-program-v1-pilot.json`: no las referencia ningún código, pero son entradas históricas de
  builds firmados (`--recipe`). Se conservan como registro y no se borran.
* `config/hardware/*.yaml` y `config/recipes/router-*.yaml` (solo aparecen en evidencias antiguas).
* `config/evals/` lo lee `core/config.py:27` (`evals_dir`) pero **no existe**. Funciona porque
  `load_suites` cae a las suites internas, pero la funcionalidad documentada de "suites YAML
  propias" no tiene ningún ejemplo.
* `evaluation_candidate_version` limitado a `5..8` (`core/config.py`, `evaluation_routes.py:44`)
  aunque ya existen recetas v9 y el programa v1.
* `.env.example` y `.env` contienen `CELTIA_ADMIN_TOKEN`, una variable de **otro proyecto**
  (CeltIA), mezclada en la configuración de HYDRA.

### 7.5 Artefactos locales y coherencia de `.gitignore`
* `data/`, `/models/` y `/runtime/` están ignorados, pero **hay 15 ficheros versionados dentro**
  (`git add -f`): `data/decision-corpus-v3/*`, `data/human-dev-v*.jsonl`, `models/hydra-decision-*`,
  `models/kev-calibrator-v3.json`, `runtime/HYDRA-Q5.Modelfile`. Es una mezcla peligrosa: el mismo
  `data/` guarda **datasets fuente** y **estado vivo con secretos** (`data/keys`, `data/secrets`,
  `data/ledger`). **Corrección:** separar `datasets/` (versionado o con Git LFS/DVC) de
  `var/`/`HYDRA_DATA_DIR` (estado, nunca versionado).
* Las evidencias de `docs/evidence` citan hashes de datasets locales no versionados
  (`data/external-evaluation-v2`, `data/hydra-instruction-v*`), así que un tercero no puede
  reproducirlas. Hace falta un manifiesto con ubicación y hash, o LFS/DVC.
* `dist/hydra_engine-1.0.0-py3-none-any.whl` y `build/` locales son de la versión **1.0.0**
  (obsoletos).
* No hay `.gitattributes`: 434 ficheros tienen CRLF en el árbol de trabajo y 24 tienen finales
  mixtos. Los `*.sh` con CRLF fallan en Docker/WSL. Añadir `* text=auto eol=lf` y
  `*.ps1 eol=crlf`.

---

## 8. Empaquetado y dependencias

| ID | Sev. | Problema | Corrección |
|---|---|---|---|
| M-16 | Medio | `package-data` declara `py.typed`, que **no existe**; falta `api/evaluation_review.html` | Crear `hydra/py.typed` y añadir el HTML |
| M-17 | Medio | `data-files` instala 6 YAML de `config/` pero no `sql/`, `config/recipes`, `config/training`, `config/models.hydra-local.yaml` ni `models.hydra-q5.yaml` | Recursos dentro del paquete con `importlib.resources` |
| B-09 | Bajo | `pyproject` `description` dice "HYDRA OS 1.0" y la versión es 1.1.0 | Alinear |
| B-10 | Bajo | Extra `training` incluye `trl` y no fija versiones; `scripts/requirements-training.txt` fija versiones pero **no** incluye `trl` ni `torch` → dos fuentes de verdad divergentes | Un solo `constraints-training.txt` referenciado desde los dos |
| B-11 | Bajo | Extra `federated = ["flwr"]`: nada importa `flwr` (solo un esqueleto JSON en `federated.py:174`) | Quitar el extra o implementar |
| B-12 | Bajo | `kev` (Apache-2.0) se parchea (`patches/kev`), pero `NOTICE` no lo menciona, ni tampoco la licencia de los pesos Qwen usados para `HYDRA.gguf` | Añadir atribuciones a `NOTICE` |
| B-13 | Bajo | Dependabot no cubre `npm` (`sdk/typescript`) | Añadir ecosistema |

---

## 9. Calidad de código (lint ampliado, tras el triage)

* **B023 (clausuras en bucles)**: `core/kernel.py:692-698`, `scheduler/invoker.py:101-102`,
  `cluster/fabric.py:240` y `cluster/nodes.py:95`. Se han revisado y **no son bugs**, porque las
  clausuras se esperan dentro de la misma iteración. Conviene ligar las variables
  (`lambda c=current: …`) para que nadie las rompa al refactorizar.
* **Mutable class defaults (RUF012)**: `corpus/gates.py:82`, `planning/simulator.py:100,156` y
  `training/lab.py:253-254`. Si se mutan, comparten estado entre instancias. Usar `ClassVar` o
  `field(default_factory)`.
* **Excepciones tragadas**: 66 `except Exception:` amplios; 13 hacen `pass`/`continue`/`return None`
  sin log (`cluster/nodes.py:129,146`, `edge/scout.py:69,97`, `model_factory/hardware.py:111`,
  `replay.py:120`, `discovery.py:120`, `corpus/synthetic.py:99`). Al menos `log.debug` con contexto.
* **`subprocess.run` sin `check`** (8 sitios fuera de tests): revisar que se compruebe
  `returncode` en todos.
* **Escrituras de estado no atómicas (M-08, Medio)**: 80 `write_text` en `hydra/` fuera de
  `training`, entre ellos ficheros de estado vivo: inventions (`ledger/ip.py:187`), ACL de secretos
  (`ip.py:479`), flags (`governance/config_registry.py:110`), políticas de secretos
  (`secrets.py:66`), experimentos del lab (`lab/lab.py:282`), glosarios
  (`edge/translation.py:73`), `applied_deltas.json` (`edge/sync.py:99`), estado de discovery y
  `runtime-manifest`. Un corte o dos escritores concurrentes dejan un JSON truncado.
  `training/evidence_io.write_json` ya es atómico, pero solo lo usa `training`, y su `.tmp` es fijo
  (dos escritores chocan). **Corrección:** un `hydra/core/atomic.py` (`NamedTemporaryFile` en el
  mismo directorio, `fsync`, `os.replace`, lock por fichero) usado por todos los stores.
* Estilo: `api/main.py` mezcla el orden de imports y le falta una línea en blanco antes de
  `class Feedback`. `evaluation_routes.py` y `web_routes.py` no siguen el formato del resto
  (sin espacios tras comas, imports desordenados). Las reglas `E4,E7,E9,F` no lo detectan:
  conviene ampliar a `I` (isort), `E3`, `B`, `UP` y `RUF100` de forma gradual.

---

## 10. Observabilidad

* **M-18 · Medio** · Los dashboards de Grafana no se cargan: `docker-compose.yml` monta los JSON en
  `/var/lib/grafana/dashboards` pero **no hay provisioning** (`provisioning/dashboards/*.yaml`,
  `provisioning/datasources/*.yaml`). Los JSON usan `${DS_PROMETHEUS}` con `__inputs` (formato de
  importación manual), que el provisioning de ficheros no resuelve.
* Histograma de confianza mal construido (M-12).
* `hydra_process_pid` sin `# TYPE`; las métricas son por proceso (con varias réplicas o workers,
  Prometheus ve series separadas sin etiqueta `instance`/`node_id`); `hydra_tool_latency_ms` se
  registra pero ningún dashboard la usa.
* Todas las métricas de dashboards se emiten (comprobado una por una), salvo el problema de
  buckets.

---

## 11. Tests y CI

* **H-02**: un test hashea los 75 GB del `models/` real y la suite pasa de unos 2 min a 16,5 min.
* **Tests no herméticos**: `tests/runtime/test_api.py` usa el singleton global `hydra.runtime.api`,
  que crea `./runtime/hydra.db` en el cwd y comparte estado entre tests.
* `kev_tests/test_reliability.py` está fuera de `testpaths` y de CI (requiere `kev` parcheado +
  torch). Hay que documentar cómo se ejecuta o añadir un job manual (`workflow_dispatch`).
* Hay tests sin trackear (`tests/test_training_program.py`, `tests/test_calibration_program.py`)
  junto a código sin trackear (`hydra/training/program.py`, `calibration.py`). Si se hace push sin
  ellos, CI no los ve.
* CI: solo Python 3.12 (la imagen usa 3.14, H-04). No compila ni prueba el SDK TS. **CodeQL solo se
  ejecuta en `main`**, no en `integration/*`, que es donde se trabaja. No hay escaneo de imagen
  (Trivy/Grype), `kubeconform`/`kube-linter` ni `terraform validate`, que habrían detectado C-03 y
  M-07. El job Docker no prueba ningún endpoint autenticado ni `hydra worker` (H-03).
* Cobertura de seguridad que falta: no hay tests para WS sin key desde una IP remota (C-02),
  `sync/import` con clave ajena (C-01), `authorized` autodeclarado (H-01) ni traversal de
  `config/{env}` (M-02).
* El README dice "136 pruebas"; hoy son **604** (599 + 5 skipped).

---

## 12. Documentación

* **51 documentos en `docs/` + 115 evidencias, sin índice.** 46 son informes fechados
  (2026-09-28 → 10-01) mezclados con documentación de referencia en la misma carpeta. Propuesta:
  `docs/reference/` (arquitectura, seguridad, API, despliegue), `docs/reports/AAAA-MM-DD/` e
  `docs/README.md` como índice.
* Duplicados o solapados: `docs/architecture.md` ↔ `docs/runtime/ARCHITECTURE.md`;
  `SECURITY.md` ↔ `docs/security.md` ↔ `docs/runtime/SECURITY.md`; `docs/INTEGRATION_PLAN.md` ↔
  `docs/MAIN_INTEGRATION_PLAN.md`; `docs/runtime/MODEL_FACTORY.md` ↔ `FACTORY_RUNTIME.md`.
* Idiomas mezclados: castellano, inglés (`docs/runtime/*`) y gallego
  (`PLAN_ADESTRAMENTO_HYDRA_2026-10-01.md`).
* Referencias rotas: `docs/MAIN_INTEGRATION_PLAN.md` → `tests/test_api_security.py` y
  `tests/test_coding_loop.py` (están en `tests/runtime/`); `docs/runtime/README.md` →
  `docs/ROADMAP.md` (está en `docs/runtime/ROADMAP.md`).
* README desactualizado o inexacto: número de pruebas; "Esquema PostgreSQL multi-nodo… ledger con
  triggers" (H-07); "Scheduler distribuido / Execution Fabric" (cola SQLite local, H-06); no
  explica qué rutas exigen admin; no menciona `/hydra/v1/models/artifacts` ni el coste de ese
  escaneo.
* No hay documentación de la API agrupada (OpenAPI se genera, pero no hay `tags` por dominio, y
  `/docs` sin auth expone la superficie completa).

---

## 13. Plan de acción priorizado

### P0: inmediato (seguridad y despliegues que no arrancan)
1. C-01: `sync/import` con claves de confianza solo del servidor y token admin.
2. C-02: WS con la misma auth y rate limit que HTTP, `compare_digest` y sin key en query string.
3. H-01: eliminar `authorized` autodeclarado y `verified=True` fijo en `/goals`.
4. C-04: `.dockerignore` en lista blanca.
5. C-03: `command`/`ENTRYPOINT` en k8s, quitar el Secret versionado y probes a `/ready`.
6. H-02: caché y `to_thread` en el escaneo de modelos; test con `tmp_path`.

### P1: próximo sprint
7. H-03 / M-16 / M-17 / H-05: recursos dentro del paquete (`schema.sql`, HTML, `py.typed`); datos
   de evaluación en `data_dir`.
8. H-04: alinear Python 3.12 en la imagen o probar 3.14 en CI; fijar digests.
9. M-01 / M-02: separar privilegios (admin) en rutas de gobierno, IP y corpus; `safe_id` en
   `config/{env}`, `flags/{name}` y `glossaries/{name}`.
10. M-08: helper de escritura atómica para todos los stores.
11. M-09 … M-15: bugs de la tabla §3.
12. CI: CodeQL en `integration/**`, kubeconform, `terraform validate`, Trivy, build del SDK TS y
    tests de seguridad nuevos.

### P2: consolidación (2–4 sprints)
13. §6: unificar `Settings` → contratos → helpers → traducción → artefactos/provenance →
    sandbox/workspace → verifier → planner → kernel, con reexportaciones temporales.
14. §4.2: API nativa única `/hydra/v1` con `APIRouter` por dominio; `/v1/*` limitado a la
    compatibilidad OpenAI; deprecaciones explícitas.
15. §5: decidir Postgres para ledger, corpus, world y fabric (implementar con migraciones) o
    eliminar las 10 tablas y corregir la documentación.
16. M-03: claves fuera de `data_dir` (keyring/KMS).
17. M-18: provisioning de Grafana y buckets por métrica.

### P3: limpieza
18. §7: borrar `hybrid_classifier.py`; mover los generadores versionados de `training/` y los
    scripts obsoletos a `research/`; consolidar `config/models.hydra-instruction-v*.yaml`;
    eliminar las recetas sin referencias; quitar `CELTIA_ADMIN_TOKEN`.
19. Separar `datasets/` de `HYDRA_DATA_DIR`; `.gitattributes`; borrar `dist/` y `build/` 1.0.0.
20. §12: índice de documentación, unificar duplicados, corregir enlaces y README.

---

## Anexo A: comandos ejecutados

```text
ruff check .                                   -> limpio
ruff check . --select F,E,W,B,UP,SIM,PL,RUF,ARG,PIE,ERA,S --statistics
pytest -q                                      -> 599 passed, 5 skipped, 992 s
git ls-files --eol | git ls-files -i -c --exclude-standard
análisis AST propio: rutas FastAPI (142), clases duplicadas (50), cuerpos de función idénticos,
módulos sin importadores, imports de terceros vs extras declarados, enlaces de documentación,
referencias a configs/scripts, métricas de dashboards vs emisión en código.
```

## Anexo B: rutas duplicadas exactas (método + path)

```text
GET  /health          main.py:109            | runtime/api.py:176   (gana main)
GET  /v1/models       main.py:213            | runtime/api.py:258   (runtime → /hydra/v1/models/artifacts)
POST /v1/translate    platform_routes.py:835 | runtime/api.py:227   (gana platform)
PUT  /v1/glossaries/{} platform_routes.py:853 | runtime/api.py:244  (gana platform)
POST /v1/tasks ≡ POST /hydra/v1/tasks         platform_routes.py:243-249 (mismo handler)
```

---

## 14. Estado tras la intervención (2026-10-01)

Verificación final: `ruff check .` limpio; `pytest` **622 passed, 5 skipped en 107 s** (antes
599/5 en 992 s); imagen Docker construida y arrancada; `docker compose config` correcto en todos los
perfiles; kubeconform **18/18 recursos válidos**; `terraform validate` correcto; SDK TS compila con
`tsc`. Se añaden 21 tests de regresión en `tests/test_security_hardening.py`.

| ID | Estado | Qué se hizo |
|---|---|---|
| C-01 | ✅ Corregido | `trusted_keys` eliminado del cuerpo (`extra="forbid"` → 422). Las claves de confianza son la del nodo y las de `HYDRA_SYNC_TRUSTED_KEYS_DIR` (por defecto `<data_dir>/keys/trusted`). El CLI tampoco confía ya en la clave incrustada en el bundle (`--trust-key` explícito). Ruta solo admin |
| C-02 | ✅ Corregido | `hydra/api/security.py`: misma autenticación HTTP/WS (sin key, solo loopback, incluidas IPv4 mapeadas), `compare_digest`, token por cabecera o subprotocolo `hydra.token.<key>` (nunca query), rate limit y comprobación de tenant en WS. SDK TS actualizado |
| C-03 | ✅ Corregido | `command: ["hydra"]` en k8s, sin Secret versionado (instrucciones `kubectl create secret`), securityContext, NetworkPolicy, imágenes por digest, caché HF, una réplica por servicio con RWO + afinidad (motivo: SQLite) |
| C-04 | ✅ Corregido | `.dockerignore` en lista blanca. Contexto de build: 1,9 MB |
| H-01 | ✅ Corregido | `authorized` en `/goals` exige el token admin |
| H-02 | ✅ Corregido | `HashCache` persistente por (ruta, tamaño, mtime) y escaneo en `asyncio.to_thread`. La validación de despliegue sigue releyendo los bytes. Tests herméticos |
| H-03 | ✅ Corregido y verificado | `sql/schema.sql` va en el wheel (`share/hydra/sql`) y el Dockerfile lo copia antes de instalar. Comprobado en la imagen. CI lo verifica |
| H-04 | ✅ Corregido | Imagen en `python:3.12-slim` (3.12.14 verificado) |
| H-05 | ✅ Corregido | ROOT de evaluación = checkout o cwd; 404 explícito sin dataset; HTML en `package-data` |
| H-06 (fabric) | ✅ Corregido (PR propio) | `PostgresWorkQueue` (psycopg 3, `FOR UPDATE SKIP LOCKED`, advisory lock para idempotencia) con el mismo contrato que SQLite; `HYDRA_FABRIC_BACKEND`; tablas `fabric_*` en `schema.sql`; suite de contrato para ambos backends, concurrencia real (8 nodos, 60 trabajos) y job de CI con PostgreSQL |
| H-07 (ledger) | ✅ Corregido (PR propio) | `PostgresLedger` sobre `ip_events`/`ledger_anchors`: advisory lock y secuencia explícita (cadena única sin huecos entre nodos), cuerpo exacto del evento para verificar, triggers contra UPDATE/DELETE/TRUNCATE, verificación compartida con el ledger de ficheros, adopción verificada del ledger existente y exportación en el backup |
| H-07 (corpus) | ✅ Corregido (PR propio) | Logs de eventos (`hydra.core.eventlog`) en la tabla `hydra_logs`: un stream por fichero del corpus, secuencia sin huecos bajo advisory lock por stream, trigger append-only, importación única y verificada de los ficheros existentes; `CorpusStore` reproduce los logs y se pone al día con las escrituras de otros nodos (antes de escribir, de cada snapshot y como mucho cada `refresh_s` al leer); ids de snapshot asignados con el stream bloqueado; backup exporta los streams; edge sync lee del log |
| H-07 (World Model) | ✅ Corregido (PR propio) | Log de deltas y snapshots en `hydra_logs` (streams `world/*`) con el mismo log de eventos que el corpus; `WorldModel` reproduce los deltas en el orden global y se pone al día antes de aplicar los suyos y como mucho cada `refresh_s` al leer. Corregido además: el cierre de relaciones se fechaba con la hora de cada *replay* (reinicio, otro nodo, time machine); ahora `KnowledgeDelta.closed_at` se fija al aplicar. El mundo provisional de `KnowledgeCompiler` (`scratch()`) ya no muta las relaciones del mundo real. Backup exporta los streams; edge sync lee del log |
| H-07 (IP) | ✅ Corregido (PR propio) | `IPRegistry` pasa de reescribir `inventions.json` entero a un log de versiones (`ip/inventions.jsonl`, fichero o `hydra_logs`); cada cambio es una lectura-modificación-escritura sobre la última versión con el stream bloqueado, así que dos nodos no generan el mismo `INV-HYDRA-nnnn` ni pierden cambios del otro. El `inventions.json` existente se convierte una vez y se conserva |
| H-07 (artefactos) | ✅ Corregido (PR propio) | Manifiestos en el log de eventos (`artifacts/manifests.jsonl`, fichero o `hydra_logs`); blobs en `hydra.artifacts.blobs`: directorio local o compartido, o bucket S3-compatible (`HYDRA_ARTIFACT_OBJECTS`, `HYDRA_S3_ENDPOINT_URL`, extra `s3`). El blob se escribe antes que el manifiesto; `verify` re-hashea en cualquier backend; restore verifica contra el almacén de blobs configurado. La sonda red-team de artefacto corrupto restaura el contenido en vez de borrarlo (antes dejaba un manifiesto sin blob y el invariante de recuperación fallaba). Al cambiar de almacén, los objetos locales existentes se copian una vez (re-hasheados; los corruptos se informan y no se copian). Los ficheros `*.env` de `data/` quedan fuera del backup salvo `--include-private-keys` |
| H-06 (outbox) | ✅ Corregido (PR propio) | Outbox de captura en la tabla `capture_outbox` (`HYDRA_OUTBOX_BACKEND`): `pending` reclama los mensajes con `FOR UPDATE SKIP LOCKED` y un lease, así que dos nodos nunca reintentan la misma escritura diferida (evento de ledger duplicado); un nodo caído libera sus mensajes al expirar el lease; los no publicados del SQLite local se importan una vez. `stats` cuenta sin reclamar (antes contaba llamando a `pending`) |
| H-06 (resto) / H-07 (resto) | ✅ Corregido | Todos los planos con estado durable funcionan sobre PostgreSQL (y blobs en S3 o volumen compartido): fabric, ledger, corpus, World Model, IP, artefactos, outbox de captura, línea runtime y registros pequeños (PRs #41–#60); `HYDRA_REQUIRE_SHARED_STATE` impide arrancar réplicas con algún plano local |
| M-01 | ✅ Corregido | `HYDRA_ADMIN_TOKEN` (`X-Hydra-Admin-Token`) en flags, config, corpus review/tombstone, datasets build, IP, releases build, lifecycle, training runs, red-team, belief confirm, edge autobuild/sync, heartbeats, lab, factory jobs, cache invalidate y `evals/run?apply`. Sin token configurado, solo loopback. El runtime admin acepta la misma cabecera. Studio tiene campo de token admin (solo `sessionStorage`) |
| M-02 | ✅ Corregido | `safe_id` en `ConfigRegistry._path` (cubre API y CLI); 400 en la API |
| M-03 | ✅ Corregido (PR propio) | `hydra.core.keystore`: env `HYDRA_KEY_*` → `HYDRA_KEYS_DIR` (fuera de data) → keyring del SO (extra `keys`); migración verificada de las claves heredadas; backup con `--include-private-keys` exporta las del keyring; Compose/k8s con volumen `/keys` propio |
| M-04 | ✅ Corregido | CSP estricta (`connect-src 'self'`, `frame-ancestors 'none'`), `nosniff`, `no-referrer`; `esc()` escapa comillas; todos los campos de tablas escapados |
| M-05 | ✅ Corregido (PR propio) | La evidencia shadow/canary se mide en servidor desde `runtime-evidence.jsonl` (errores y latencias por llamada, fallos de canary incluidos), contando solo desde el inicio de cada fase (offset del log). `/canary` y `/activate` no aceptan cifras; `GET .../evidence` muestra el progreso |
| M-06 | ✅ Parcial | Prometheus y Grafana solo en 127.0.0.1, contraseña de Grafana por `.env`, comentarios corregidos |
| M-07 | ✅ Corregido | Namespace antes que los recursos (`depends_on`), DRA opcional (`enable_dra`), sin secretos en el state |
| M-08 | ✅ Corregido | `hydra/core/atomic.py` (temporal único + fsync + `os.replace` + reintentos en Windows) en inventions, ACL, flags, políticas y almacén de secretos, lab, glosarios, sync, discovery, autobuild/.env, perfiles y estado de releases. `evidence_io.write_json` lo reutiliza |
| M-09 | ✅ Corregido | `/v1/responses` → 502/503 con `HydraTaskFailed` |
| M-10 / M-11 | ✅ Corregido | Referencias fuertes a las tareas (jobs y export OTLP); historial de jobs acotado (500) |
| M-12 | ✅ Corregido | Buckets por métrica (`hydra_confidence_pct` en %); `# TYPE` de `hydra_process_pid` |
| M-13 | ✅ Corregido | La configuración runtime lee `.env` con la misma precedencia que la plataforma |
| M-14 | ✅ Parcial | `HYDRA_RUNTIME_DIR` configurable para todo el estado runtime (por defecto `runtime`, sin cambio). Los tests usan un directorio privado, lo que elimina el fallo intermitente de `test_runtime_anchor`. Los singletons al importar siguen ahí |
| M-15 | ✅ Corregido | `hydra/training/json_match.py`; el script lo reutiliza |
| M-16 / M-17 | ✅ Corregido | `py.typed`, HTML de evaluación, configs locales y esquema en la distribución |
| M-18 | ✅ Corregido | Provisioning de datasource (`uid: prometheus`) y dashboards; JSON sin `__inputs` |
| B-01 | ✅ Parcial | `internal_api_key` vacío por defecto (sin cabecera `Bearer internal`). `/metrics` y `/health` siguen abiertos por diseño (Prometheus) |
| B-02 | ✅ Corregido | Versiones de pytest de la imagen sandbox alineadas. **Hay que reconstruirla**: `docker build -t hydra-sandbox:py312-v3 -f infra/sandbox/Dockerfile .` |
| B-03 | ✅ Corregido | Una sola detección de loopback (`ipaddress`, IPv4 mapeada) |
| B-05 | ✅ Corregido | Modelo desconocido → 400 en `/v1/responses` |
| B-06 / B-07 | ✅ Corregido | `assert` → `ValueError`; `eval` → `operator` |
| B-08 | — | Cambio en curso del autor (`train_lora.py`); no se toca |
| B-09 | ✅ Corregido | Descripción del paquete 1.1 |
| B-10 / B-11 | 📄 Aceptado | `requirements-training.txt` refleja el entorno local real (sin TRL); el extra `federated` es un punto de extensión documentado |
| B-12 | ✅ Corregido | NOTICE con kev (Apache-2.0) y pesos Qwen |
| B-13 | ✅ Corregido | Dependabot `npm`; lockfile del SDK TS; job de CI |
| §6 duplicación | ⏳ Pendiente | Consolidar las dos líneas es una refactorización por fases (plan en §6); no se mezcla con correcciones |
| §7 código muerto | ✅ Parcial | Borrado `training/hybrid_classifier.py`. Inventario de scripts en [`scripts/README.md`](../scripts/README.md). Mover los generadores versionados de `training/` queda pendiente |
| §7.5 | ✅ Parcial | `.gitattributes` (LF; `.ps1` CRLF); `CELTIA_ADMIN_TOKEN` fuera de `.env.example`. **Tu `.env` local aún lo contiene: retíralo tú** |
| §11 CI | ✅ Corregido | CodeQL en `integration/**`; jobs `manifests` (kubeconform, compose, terraform) y `sdk-typescript`; el job Docker verifica worker, esquema y recursos empaquetados |
| §12 docs | ✅ Corregido | Índice [`docs/README.md`](README.md), enlaces corregidos, README actualizado (pruebas, admin, persistencia real, límites) |

**Acciones del operador tras desplegar:** definir `HYDRA_ADMIN_TOKEN` en cada entorno remoto (sin él,
las rutas de operador solo responden a loopback); instalar en `<data_dir>/keys/trusted/` las claves
públicas de los nodos edge que deben poder sincronizar; reconstruir la imagen sandbox; crear los
Secrets de k8s con `kubectl create secret` antes de aplicar los manifiestos.
