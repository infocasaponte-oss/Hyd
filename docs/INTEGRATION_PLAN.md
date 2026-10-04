# Plan de integración: HYDRA-SO (`main`) + HYDRA 1.0 (`integration/hydra-1.0`)

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha de auditoría: 29/09/2026 · Repositorio: `github.com/infocasaponte-oss/HYDRA-SO` y copia local `D:\HYDRA`.

## 1. Dictamen

Las dos líneas se pueden unir **sin conflictos y conservando toda la historia** (392 + 16 commits). No hace
falta reescribir historia ni hacer `push --force`. La clave es mover primero los módulos de `main` a un
espacio de nombres propio, `hydra.runtime`, en un commit de la propia línea `main`. Después se fusiona con
`--allow-unrelated-histories`.

Está comprobado con una prueba en seco:

| Comprobación | Resultado |
|---|---|
| `git merge-tree --write-tree --allow-unrelated-histories` | código de salida 0, **0 conflictos** (árbol `43d10fc`) |
| Merge real en rama local `prep/merge-dryrun` | commit `d3c0323`, sin intervención manual |
| Suite completa del árbol unificado (Windows, Python 3.12) | **324 passed, 2 skipped, 4 failed** |
| Los 4 fallos | 3 son fallos previos de `main` que solo ocurren en Windows (A5) y 1 es un bug latente de `main` (A4); ninguno lo introduce la fusión |

## 2. Inventario

| Rama remota | Commit | Relación | Contenido |
|---|---|---|---|
| `main` (por defecto) | `48d0f3a` | **sin ancestro común** con las demás | HYDRA-SO v0.4.0.dev0: 111 módulos planos en `hydra/`, 7.240 líneas, 90 ficheros de test (178 tests), CI verde en Linux (379 ejecuciones) |
| `hydra-1.0` | `83db303` | ancestro de `integration` | HYDRA 1.0.0: plataforma por paquetes, ~26.600 líneas |
| `integration/hydra-1.0` | `5e3ddf5` | `hydra-1.0` + 7 commits | CI Python 3.12, autenticación remota y rate limit (portado de `main`) |
| `codex/finish-hydra-gguf` | `185fdd7` | `integration` + 8 commits | Fábrica HYDRA.gguf, gates que rechazan evaluaciones incompletas, entrenamiento, cabeceras |

`D:\HYDRA` está en `codex/finish-hydra-gguf`, sin cambios pendientes y sincronizada con el remoto.
No hay pull requests ni protección de ramas.

## 3. Hallazgos de la auditoría

| # | Severidad | Hallazgo | Acción en el plan |
|---|---|---|---|
| A1 | Alta | `main` y la línea 1.0 no comparten historia: un PR entre ellas no es fusionable tal cual | Fases 2–3 |
| A2 | Alta | Colisiones de rutas: 9 módulos de `main` tienen el mismo nombre que paquetes locales (`api`, `artifacts`, `corpus`, `model_factory`, `observability`, `policy`, `provenance`, `router`, `tools`). Un merge directo haría que el paquete ocultara al módulo y rompería `main`. Además, 12 ficheros coinciden (`README.md`, `pyproject.toml`, `.gitignore`, `.env.example`, `hydra/__init__.py`, `hydra/cli.py`, `hydra/language.py`, `hydra/replay.py`, `docs/architecture.md` en Windows, `tests/test_api.py`, `tests/test_kernel.py`, `tests/test_tools.py`) | Fase 2 (espacio de nombres `hydra.runtime`) |
| A3 | **Alta (decisión del titular)** | El repositorio es **público**, pero el software es propietario («todos los derechos reservados») e incluye el ledger de invenciones y documentación de auditoría. `main` no tiene `LICENSE` ni cabeceras de copyright | Fase 0 y Fase 7 |
| A4 | Media | Bug en `main` (`outbox.py`): `pending()` ordena por `created_at, id` y `id` es un UUID aleatorio. Si dos marcas de tiempo empatan (habitual en Windows), el orden de entrega es aleatorio. `test_terminal_commit_is_atomic_with_outbox` falla 5/5 en Windows | Fase 1: columna `seq INTEGER` autoincremental y `ORDER BY seq` |
| A5 | Media | `main` falla en Windows: (a) `ToolRuntime` lanza el subproceso con un entorno reducido sin `SYSTEMROOT` (WinError 10106); (b) 2 tests crean symlinks sin privilegio (WinError 1314) | Fase 1: conservar `SYSTEMROOT`/`WINDIR` en Windows; `skipif` si no se pueden crear symlinks |
| A6 | Media | Variables de entorno: `HYDRA_SANDBOX_IMAGE` significa cosas distintas (`hydra-sandbox:py311-v2` endurecida frente a `python:3.12-slim`). Hay dos sistemas de autenticación: `HYDRA_API_KEY` (local) y `HYDRA_API_TOKEN`/`HYDRA_ADMIN_TOKEN` (`main`). `HYDRA_API_RATE_LIMIT_PER_MINUTE` coincide y es compatible | Fase 6 |
| A7 | Media | Empaquetado incompatible: `hydra-so` 0.4.0.dev0 con hatchling y Python ≥3.11, frente a `hydra-engine` 1.0.0 con setuptools y Python ≥3.12. Las dependencias de `main` (fastapi, httpx, pydantic) ya están incluidas en las locales | Fase 7: se queda `pyproject` local |
| A8 | Media | Rutas HTTP que chocan: `GET /health`, `GET /v1/models` y `POST /v1/translate` tienen contratos distintos; glosarios usan `PUT /v1/glossaries/{id}` (`main`) frente a `POST /v1/glossaries/{name}` | Fase 5 |
| A9 | Baja | La CI local solo se dispara en `hydra-1.0`/`integration` o en PR: los 8 commits de `codex/finish-hydra-gguf` **no tienen CI**. La CI de `main` usa `ruff` y la local no | Fase 7 |
| A10 | Baja | Ramas: `hydra-1.0` queda obsoleta (ancestro de `integration`); la rama local `codex/...` seguía una rama remota con otro nombre; `main` no está protegida | Fases 0 y 8 |
| A11 | Info | Unos 40 conceptos están duplicados entre las dos líneas (ver §5.4) | Fase 4 |

## 4. Estrategia elegida y alternativas descartadas

**Elegida: espacio de nombres + merge de historias no relacionadas.**

1. En una rama que sale de `main`, un único commit `git mv`:
   - `hydra/*.py` → `hydra/runtime/`
   - `tests/*.py` → `tests/runtime/`
   - `docs/*.md`, `README.md` y `SECURITY.md` → `docs/runtime/`
   - Se reescriben los imports `hydra.X` → `hydra.runtime.X` (187 ficheros).
   - Se eliminan los ficheros raíz que sustituye la línea 1.0.
2. Merge de esa rama en `integration/hydra-1.0` con `--allow-unrelated-histories`. No hay conflictos porque
   ya no quedan rutas en común.
3. PR `integration/hydra-1.0` → `main`: `main` es ancestro del merge, así que es un avance normal, sin `--force`.

`git log --follow hydra/runtime/outbox.py` conserva la historia de los 392 commits.

| Alternativa | Motivo del descarte |
|---|---|
| Merge directo con `--allow-unrelated-histories` | 12 conflictos add/add y 9 módulos ocultados por paquetes: `main` queda roto |
| Sustituir `main` con `push --force` | Destruye la rama por defecto y deja sin referencia 392 commits con CI verde |
| Subcarpeta `hydra-so/` independiente | Dos paquetes `hydra` en el mismo repositorio: imports ambiguos y nada integrado |
| Cherry-pick o reescritura | Se pierde la trazabilidad commit a commit, necesaria para el ledger de IP |

## 5. Plan por fases

Cada fase termina con la suite verde en CI (Linux) y en local (Windows) antes de pasar a la siguiente.

### Fase 0 — Decisiones y preparación (titular)
- Decidir la visibilidad del repositorio. **Recomendado: privado** mientras haya invenciones en revisión (A3).
- Congelar `main` durante la integración y activar la protección de rama (PR obligatorio + CI).
- Fusionar `codex/finish-hydra-gguf` → `integration/hydra-1.0`. Es un avance rápido: `git push origin codex/finish-hydra-gguf:integration/hydra-1.0`.
- Alinear el seguimiento local: `git branch -u origin/integration/hydra-1.0` o trabajar directamente en `integration`.

### Fase 1 — Estabilizar `main` antes de moverlo
- A4: añadir `seq INTEGER PRIMARY KEY AUTOINCREMENT` (o un contador monotónico) en `outbox` y ordenar por él, con migración para bases existentes.
- A5: conservar `SYSTEMROOT`, `WINDIR` y `COMSPEC` en el entorno reducido de `ToolRuntime` en Windows; `pytest.mark.skipif` en los tests de symlinks cuando `os.symlink` no esté permitido.
- Salida: `main` en verde en Linux (CI) y en Windows (178/178 o con los skips documentados).

### Fase 2 — Mover `main` a `hydra.runtime` (script validado en seco)
Rama `prep/runtime-namespace`, que sale de `main`. Contenido del commit:

| Origen (`main`) | Destino |
|---|---|
| `hydra/*.py` (110 módulos) | `hydra/runtime/*.py` |
| `tests/*.py` (90) | `tests/runtime/*.py` (+ `__init__.py` para evitar choques de nombre) |
| `docs/*.md`, `README.md`, `SECURITY.md` | `docs/runtime/` |
| `infra/sandbox/`, `scripts/run_api.sh` | sin cambios (no chocan) |
| `pyproject.toml`, `.gitignore`, `.env.example`, `.github/workflows/ci.yml`, `hydra/__init__.py` | eliminados; su contenido útil se incorpora en la Fase 7 |

- Imports reescritos por expresión regular (`hydra.X` → `hydra.runtime.X`, incluidas las cadenas de `monkeypatch`).
- `from hydra import __version__` se mantiene: lo aporta el paquete raíz.
- Cabecera de copyright en todos los ficheros movidos.
- Salida: `tests/runtime` en verde con el `pyproject` local.

### Fase 3 — Merge sin conflictos
```bash
git switch integration/hydra-1.0
git merge-tree --write-tree --allow-unrelated-histories HEAD prep/runtime-namespace   # debe salir 0
git merge --allow-unrelated-histories --no-ff prep/runtime-namespace \
  -m "merge: integrate HYDRA-SO runtime line under hydra.runtime"
pytest -q
```
Salida: 0 conflictos y suite completa en verde (objetivo: ≥ 328 tests tras la Fase 1).

### Fase 4 — Consolidar por planos
Durante la transición, `hydra.runtime` sigue funcionando por sí solo. Cada fila es un PR pequeño con tests.
«Adoptar» significa que la pieza de `main` pasa a ser la implementación de referencia; «Retirar» significa
borrarla cuando el equivalente local cubra sus tests.

#### 5.4 Mapa de consolidación

| Módulos de `main` | Equivalente local | Acción |
|---|---|---|
| `outbox`, `outbox_dispatcher`, `outbox_worker`, `outbox_metrics`, `startup_recovery`, `capture_uow` | `core/capture`, `cluster/fabric` | **Adoptar**: outbox transaccional con cola de mensajes fallidos (dead-letter); `CapturePipeline` escribe a través de él |
| `deployment*` (8), `traffic_router`, `promotion`, `promotion_gate` | ciclo de vida de modelos (`/models/{id}/lifecycle`), `training` Promotion Gate | **Adoptar** como plano de despliegue (shadow/canary/rollback con evidencias persistentes); el Training Lab promueve a través de él |
| `gpu_telemetry`, `health_gate`, `readiness`, `runtime_health*`, `process_supervisor`, `build_supervisor`, `physical_*`, `runtime_bridge`, `runtime_executor`, `runtime_events`, `runtime_evidence` | `edge/autobuild`, `cluster/nodes` | **Adoptar**: telemetría que falla cerrada, health 2xx y supervisión de procesos pasan a ser el backend de medición de `edge` |
| `gguf`, `llama_factory`, `quant_profiles`, `autoquant`, `model_scout`, `hardware`, `variant_runner`, `http_benchmark` (retirado: nunca se usó ni tenía test propio), `benchmark_*`, `benchmarking`, `pareto`, `optimization_report` | `model_factory/*`, `training/autoquant`, `edge/scout`, `edge/profiles` | **Fusionar**: el parser GGUF y el benchmark en streaming de `main` (TTFT medido) sustituyen a las estimaciones locales; se conserva la API local |
| `code_agent`, `coding_loop`, `code_context`, `code_verification`, `code_replay`, `patching`, `static_analysis` | `planning/runner` (GoalRunner), `tools/workspace` | **Adoptar** la verificación por capas (baseline que falla, test dirigido, suite completa, sintaxis) dentro de GoalRunner |
| `workspaces`, `workspace_hash`, `sandbox` (OCI + preflight), `tool_runtime`, `tool_audit`, `tools`, `policy`, `security`, `security_audit` | `tools/*`, `sandbox`, `governance/*`, `policy/kernel` | **Fusionar**: los límites de ficheros, bytes y symlinks y la imagen sandbox endurecida entran en `tools.workspace`; las políticas pasan a `governance` |
| `privacy`, `corpus`, `corpus_quality`, `learning_capture`, `dataset_factory` | `corpus/*` | **Fusionar**: `PrivacyScanner` como gate adicional; los niveles de calidad se mapean a `corpus.gates` |
| `events`, `hash_chain`, `provenance`, `replay`, `replay_executor`, `replay_integrity`, `replay_runtime`, `artifacts` | `ledger/chain`, `artifacts/store`, `replay.py`, `provenance/` | **Adaptador**: los eventos de runtime se anclan en el ledger firmado; después se retira `hash_chain` |
| `beliefs` | `world/model` (Belief Graph) | **Retirar** tras migrar sus tests |
| `rate_limit`, `circuit_breaker` | `governance/rate_limit` (ya portado), `registry/circuit_breaker` | **Retirar** |
| `translation`, `language` | `edge/translation`, `hydra/language.py` | **Fusionar**: troceado por fragmentos y `GlossaryStore` de `main` con los glosarios locales |
| `kernel`, `router`, `planner`, `contracts`, `state`, `model_registry`, `provider`, `executor`, `verifier`, `budgets` | `core/*`, `router/*`, `registry/*`, `verification/*` | **Retirar** cuando `/hydra/v1/tasks/route` y `/execute` usen el kernel local (Fase 5) |
| `observability`, `operating_metrics`, `metrics_store` | `observability/tracing`, `telemetry/metrics` | **Fusionar** métricas operativas en Prometheus/OTLP |
| `config` | `core/config` (pydantic-settings) | **Migrar** los campos (Fase 6) |
| `cli` (`profile`) | `cli_platform` | **Fusionar** el subcomando |

### Fase 5 — API unificada
- Convertir `hydra/runtime/api.py` en un `APIRouter` y montarlo en la app local.
- Endpoints de `main` que se incorporan tal cual: `/ready`, `/v1/chat`, `/hydra/v1/tasks/route`, `/hydra/v1/tasks/execute`, `/hydra/v1/admin/*` (métricas, replay, despliegues, dead-letters) y `/hydra/v1/coding/verify-fix`.
- Colisiones:
  - `/health`: una sola implementación que combina las dos respuestas.
  - `/v1/models`: formato OpenAI (el local) con los campos de `main` como extensión.
  - `/v1/translate`: contrato local, que acepta el esquema de `main`.
  - Glosarios: aceptar `PUT` y `POST`.
- Tests de contrato de cada ruta con los clientes de `tests/runtime/test_*api*.py`.

### Fase 6 — Configuración, autenticación y variables de entorno
- Pasar los campos de `hydra.runtime.config` a `Settings` (pydantic) con los mismos nombres de variable.
- `HYDRA_SANDBOX_IMAGE`: adoptar la imagen endurecida `infra/sandbox` (reconstruida para Python 3.12) como valor por defecto; `python:3.12-slim` queda solo para desarrollo.
- Autenticación: una sola política. `HYDRA_API_TOKEN` para el tráfico normal y `HYDRA_ADMIN_TOKEN` para `/admin`; `HYDRA_API_KEY` se mantiene como alias obsoleto. Se conserva el comportamiento de rechazar el acceso remoto sin autenticación.
- `.env.example` y `.gitignore`: unión de ambos (`*.log`, `.ruff_cache/`, `.DS_Store`, `repositories/`).

### Fase 7 — Empaquetado, CI, documentación y licencia
- Se queda el `pyproject` local (`hydra-engine`, setuptools, Python ≥3.12); versión **1.1.0** tras la fusión.
- CI en todas las ramas y PR:
  - Matriz de Python 3.12 en Ubuntu y Windows.
  - `ruff check`, `compileall` y `pytest`.
  - Smoke test del wheel instalado fuera del árbol fuente.
- `LICENSE`, `NOTICE` y cabecera de copyright en el 100 % de los ficheros, con un test que lo compruebe.
- Documentación: `docs/runtime/*` se enlaza desde `docs/architecture.md`, con una tabla de qué plano absorbe cada pieza.

### Fase 8 — Promoción y limpieza
- PR `integration/hydra-1.0` → `main` con CI verde: se fusiona sin `--force`.
- Etiqueta `v1.1.0`.
- Borrar las ramas `hydra-1.0`, `codex/finish-hydra-gguf` y `prep/*`.
- `main` queda protegida.

## 6. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Rutas o variables de entorno que cambian de comportamiento para clientes de `main` | Tests de contrato (Fase 5) y alias obsoletos durante una versión |
| Doble fuente de verdad (outbox SQLite, ledger JSONL, fabric) durante la Fase 4 | Un único escritor por concepto; adaptadores de solo lectura hasta retirar el duplicado |
| Otro agente escribiendo en `D:\HYDRA` durante la integración | Trabajar en ramas y worktrees propios; comprobar `git status` antes de cada commit |
| Historia más difícil de leer tras el `git mv` masivo | Commit de movimiento aislado, sin cambios de lógica; `git log --follow` conserva el rastro |
| Fallos que solo aparecen en Windows | CI en Windows (Fase 7) |

## 7. Criterios de aceptación

1. `main` contiene las dos historias completas (392 de `main` + 16 de la línea 1.0 + movimiento y merge: `git rev-list --count main` ≥ 410) sin ningún `push --force`.
2. Suite completa en verde en Ubuntu y Windows; ningún test de `main` se ha eliminado sin sustituto.
3. Cada fila del mapa §5.4 está cerrada: adoptada, fusionada o retirada con tests equivalentes.
4. Una sola app FastAPI con todas las rutas de ambas líneas y tests de contrato.
5. `hydra doctor`: 10/10 invariantes en PASS; red team 12/12.
6. Licencia y cabeceras al 100 %; decisión de visibilidad del repositorio tomada.

## 8. Estado de la ejecución (29/09/2026)

| Fase | Estado | Evidencia |
|---|---|---|
| 0 | Hecho | `codex/finish-hydra-gguf` avanzado en `integration/hydra-1.0`. El repositorio sigue público por decisión del titular: en privado, la CI de Actions no arranca sin plan de pago. `main` protegida (PR obligatorio, checks requeridos, sin force-push ni borrado) |
| 1 | Hecho | `f8bd276` outbox FIFO (con test que reproduce el empate), `cc953dc` entorno de Windows, `add1047` symlinks |
| 2 | Hecho | `bf9bbd1` movimiento (198 renombrados, sin cambios de lógica), `cc28a8f` cabeceras |
| 3 | Hecho | `c9efbd8`: merge sin conflictos; suite 327 passed; CI de Linux en verde |
| 4 | Hecho (ver §5.4) | Retirados: rate limit, circuit breaker, idioma, perfiles de hardware. Adoptados: límites de workspace, detector de privacidad, límites GGUF, telemetría de VRAM, presupuestos de traducción, outbox del capture, verificación por capas en GoalRunner. Adaptadores: anclaje de cadenas en el ledger, creencias hacia el World Model, puente de despliegue HYDRA.gguf, métricas del outbox en Prometheus |
| 5 | Hecho | `57533d2`: un solo gateway con 17 rutas runtime montadas; `/v1/models` del runtime pasa a `/hydra/v1/models/artifacts` |
| 6 | Hecho | Un único token (`HYDRA_API_KEY`/`HYDRA_API_TOKEN`; cabeceras Bearer, X-API-Key y X-Hydra-Token); `.env.example` unificado; imagen `hydra-sandbox:py312-v3` construida y con preflight OK |
| 7 | Hecho | 1.1.0; ruff limpio; CI en Ubuntu y Windows en cada push y PR; smoke test del wheel fuera del árbol; test de cabeceras de copyright (482/482 ficheros) |
| 8 | Hecho | Continuó en [MAIN_INTEGRATION_PLAN.md](MAIN_INTEGRATION_PLAN.md): `main` avanzó con #5–#9 y se fusionó primero en la integración. PR #13 fusionado con merge commit (`c234b35`), etiqueta `v1.1.0` y ramas fusionadas borradas |

Fallos reales que la integración sacó a la luz y quedaron corregidos:
- Outbox con orden aleatorio.
- WorkspaceManager de la plataforma: `task_id` y rutas de ficheros podían salir del directorio, y la copia seguía symlinks.
- Lector GGUF sin límites (asignaciones de exabytes, bucles de 2^60 elementos).
- Una GPU sin telemetría se leía como 0 MB de VRAM, y las GPU de 4 GB se degradaban a `cpu_only`.
- Párrafos de traducción sin trocear.
- Escrituras del capture perdidas en silencio si fallaban.
- Test de laboratorio intermitente por la latencia.

Queda deliberadamente en `hydra.runtime`:
- `kernel`, `router`, `planner`, `contracts` y `executor`, que sirven el contrato estable de `/hydra/v1/tasks/route|execute`.
- `config`, un dataclass que ya comparte nombres de variable con los `Settings` de la plataforma.
- El formato de los stores JSONL de replay.

Retirarlos exige versionar ese contrato de API.

## 9. Estado de la prueba en seco

Las ramas de la prueba en seco se borraron; la ejecución real rehízo las Fases 2–3 con el mismo script. Estado original:

- `prep/runtime-namespace` (`56a260e`): `main` movido a `hydra.runtime`.
- `prep/merge-dryrun` (`d3c0323`): merge con `codex/finish-hydra-gguf`.

Se pueden borrar sin consecuencias: `git worktree remove` + `git branch -D`.
