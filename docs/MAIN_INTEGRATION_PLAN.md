# Plan de integración de HYDRA 1.1 en `main`

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Auditoría del 29/09/2026 sobre `github.com/infocasaponte-oss/HYDRA-SO` y la copia local `D:\HYDRA`.
Continúa [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md): allí las dos líneas se unieron en `integration/hydra-1.0`.
Este documento cubre el último paso, llevar esa rama a `main`.

## 1. Dictamen

La integración en `main` es viable **sin `push --force` y sin perder historia**, pero ya no puede ser un avance
rápido. Mientras se unían las líneas, `main` recibió 5 PRs de seguridad (#5–#9). El camino es:

1. Fusionar `main` en la rama de integración, resolviendo 6 conflictos conocidos.
2. Abrir un PR `integration/hydra-1.0` → `main`.

Comprobaciones hechas en local:

| Comprobación | Resultado |
|---|---|
| `git merge-tree` de `origin/main` sobre la integración local | 6 conflictos, todos resolubles (§4); el resto de cambios de `main` se aplica solo sobre `hydra/runtime/*` |
| Suite en la integración local (HEAD `8da5ceb`) | **403 passed, 5 skipped**; `ruff` limpio |
| La misma suite con pytest 9.1.1 y pytest-asyncio 1.4.0 (subida que trae `main`) | **403 passed**; compatible |
| `pip-audit` en un entorno limpio con `.[dev]` y setuptools ≥ 83 | **Sin vulnerabilidades conocidas** |
| CI de `main` (`a3ea0eb`): CI + CodeQL | verde |
| CI de `integration/hydra-1.0` (`500e991`): Ubuntu + Windows | verde |

## 2. Inventario

| Referencia | Commit | Estado | Contenido |
|---|---|---|---|
| `main` | `a3ea0eb` | CI y CodeQL verdes | Línea HYDRA-SO + #5 cierre de ejecución en host y ruta de tareas protegida, #6 rollback atómico de parches, #7 CI endurecida (pip-audit, build, smoke), #8 CodeQL, #9 Dependabot |
| `integration/hydra-1.0` (remota) | `500e991` | CI verde | HYDRA 1.1: plataforma + línea runtime; 46 commits por delante de la base común y 5 por detrás de `main` |
| `integration/hydra-1.0` (**local**) | `8da5ceb` | **9 commits sin publicar** | 36 ficheros, +2.845 líneas: capa de decisión local, evaluación del piloto HYDRA frente a la base, build GGUF automatizado, rutas integradas endurecidas |
| PR #4 `security/audit-hardening-2026-09` → integración | `0ca67f6` | abierto, **CI roja** (pip-audit) | Endurecimiento sobre `hydra/runtime/*`: rollback atómico en `patching.py`, `test_tool_runtime.py`, CodeQL |
| PR #1 `audit/security-hardening-2026-09-29` → integración | `56ce1ae` | abierto | Subconjunto de #4 |
| PR #2 `fix/audit-hardening-2026-09` → `main` | `29dbb81` | abierto | Variante de #5/#6/#7 sobre las rutas planas (13 commits por delante, 5 por detrás) |
| PRs #10–#12 (Dependabot) → `main` | — | abiertos | `actions/checkout` v7, `actions/setup-python` v7, `codeql-action` v4 |
| `hydra-1.0`, `codex/finish-hydra-gguf`, `security/*` ya fusionadas | — | — | Contenidas en `main` o en la integración |

## 3. Hallazgos

| # | Severidad | Hallazgo | Acción |
|---|---|---|---|
| H1 | Alta | `main` avanzó 5 commits (#5–#9): el avance rápido de integración → `main` ya no es posible | Paso B |
| H2 | **Alta** | 9 commits de la integración solo existen en `D:\HYDRA`: sin copia remota y sin CI | Paso A, lo primero |
| H3 | Media | 6 conflictos al fusionar `main`: `ci.yml`, `pyproject.toml`, `hydra/runtime/{api,coding_loop,tool_runtime}.py`, `tests/test_tools.py` | §4 |
| H4 | Media | Git aplica el cambio de `main` en `tests/test_tools.py` sobre el **test de la plataforma**, porque esa ruta existe en ambas líneas. Su destino real es `tests/runtime/test_tools.py` | §4, fila 6 |
| H5 | Media | La reubicación reescribió **33 cadenas de datos**, no solo el `producer` de `coding_loop`: tipos de evento de auditoría (`hydra.security.admin_access`), productores de eventos (`hydra.code_agent`, `hydra.kernel`, `hydra.outbox`…) y nombres de span (`hydra.router`, `hydra.planner`…). Los eventos registrados tras la integración habrían llevado nombres distintos de los de HYDRA-SO | Restauradas todas en el merge del paso B (`70ea6fb`); un script compara cada literal con la base `48d0f3a` |
| H6 | Media | PRs #1, #2 y #4 solapan con lo ya fusionado (#5–#7). Solo #4 aporta algo nuevo para la línea integrada: rollback atómico en `patching.py` y sus tests | Paso C |
| H7 | Media | `pip-audit` falla si setuptools < 83 (PYSEC-2025-49, PYSEC-2026-3447): es la causa de la CI roja de #4 | La CI unificada instala `setuptools>=83` antes de auditar |
| H8 | Media | La CI de `main` usa Python 3.11 y un solo SO. La integración exige Python ≥ 3.12: tras la fusión, esa CI fallaría | CI unificada (§4, fila 1) |
| H9 | Baja | Los PRs de Dependabot #10–#12 editan la CI de `main`, que se sustituye | Aplicar las versiones en la CI unificada; cerrar los PRs y dejar que Dependabot los regenere |
| H10 | Info | El pytest global de esta máquina lista vulnerabilidades en `python-jose` y `ecdsa`: son paquetes ajenos a HYDRA, no aparecen en el entorno limpio | Ninguna |
| H11 | Resuelto | `main` protegida en el paso E. El repositorio sigue público por decisión del titular: en privado, Actions no arranca sin plan de pago | Paso E |

## 4. Resolución de conflictos (fusión de `main` en la integración)

| # | Fichero | Qué hizo `main` | Qué hizo la integración | Resolución |
|---|---|---|---|---|
| 1 | `.github/workflows/ci.yml` | pip-audit, `python -m build`, smoke con `hydra --help`, setuptools ≥ 83; Python 3.11, solo Ubuntu | Matriz Ubuntu + Windows con 3.12, ruff, versión frente a `pyproject`, smoke con tarea offline | **Unir**: matriz 3.12 + ruff + compileall + tests + `pip install -U "setuptools>=83" pip-audit` + `pip_audit --skip-editable` + `python -m build` + smoke combinado. Adoptar `checkout@v7`, `setup-python@v7` (Dependabot) |
| 2 | `pyproject.toml` | dev: `pytest>=9.0.3,<10`, `pytest-asyncio>=1.4,<2` | `pyproject` de hydra-engine 1.1.0 (setuptools, ruff, 3.12) | **Integración** + esas dos versiones de dev (verificado: 403 passed) |
| 3 | `hydra/runtime/api.py` | `/hydra/v1/tasks/route` exige token y rate limit | Mismo cambio (`9cd4898`, local) | Conflicto solo textual: queda el código de la integración, que es equivalente |
| 4 | `hydra/runtime/coding_loop.py` | Rollback atómico de parches rechazados (#6) | Solo imports `hydra.runtime.*` y el `producer` | **`main`** + reescritura de imports a `hydra.runtime.*`; `producer="hydra.coding_loop"` (H5) |
| 5 | `hydra/runtime/tool_runtime.py` | `python.test` deja de ejecutarse en el host (falla cerrado) | Variables de Windows para el subproceso | **`main`**: el subproceso desaparece, así que el ajuste de Windows sobra; imports `hydra.runtime.*` |
| 6 | `tests/test_tools.py` | Tests del fallo cerrado de `python.test` | Es el test de la **plataforma** | Mantener el de la plataforma y **llevar el cambio de `main` a `tests/runtime/test_tools.py`** (H4) |

Se aplican solos, por detección de renombres:
- `tests/test_api_security.py` → `tests/runtime/`;
- `tests/test_coding_loop.py` → `tests/runtime/`;
- `.github/workflows/codeql.yml` y `.github/dependabot.yml`.

Tras resolver:
- `ruff check .`, suite completa y `pip-audit` en un entorno limpio;
- `git grep -n "from hydra\.\(api\|coding_loop\|tool_runtime\|patching\) import"` no debe devolver nada: ningún import plano residual.

## 5. Pasos

**Estado:**
- **A:** hecho. `3ec4035` publicado; CI verde en Ubuntu y Windows.
- **B:** merge hecho en `merge/main-into-integration` (`70ea6fb`, padres `3ec4035` + `a3ea0eb`), con 407 passed, ruff limpio y pip-audit limpio. Integración avanzada hasta ese merge.
- **C:** parte técnica hecha. De #4 se adopta `PatchTool`, que restaura los ficheros tocados cuando un parche falla o crea un symlink y añade `reverse()`, junto con sus tests (`6ab71d8`). No se adopta su `python.test` dentro del sandbox OCI: se mantiene el fallo cerrado revisado en #5, y cambiarlo es decisión del titular. #1, #2 y #4 cerrados con comentario; también #10–#12 de Dependabot.
- **D:** hecho. Rama congelada `release/1.1.0` y PR #13 → `main`. Antes de fusionar se corrigieron los hallazgos reales de CodeQL: rutas de la API limitadas a `HYDRA_REPOSITORIES_ROOT` (`4230f90`) y mensajes de error públicos (`c7d054a`). Los falsos positivos se descartaron con justificación. Fusionado con merge commit por el titular: `c234b35`.
- **E:** hecho. Etiqueta `v1.1.0`; `main` protegida (PR obligatorio, checks `test` ×2 y `Analyze Python`, sin force-push ni borrado); 11 ramas fusionadas o cerradas borradas. Siguen `integration/hydra-1.0` y `codex/finish-hydra-gguf` por el trabajo de otro agente.

### Paso A — Asegurar el trabajo local
1. Publicar los 9 commits: `git push origin integration/hydra-1.0` y esperar la CI verde (Ubuntu + Windows).
2. Si alguno no debe ir a la integración, publicarlo antes en una rama propia y sacarlo con `git revert`, nunca reescribiendo historia publicada.

### Paso B — Fusionar `main` en la integración
```bash
git switch -c merge/main-into-integration origin/integration/hydra-1.0
git merge origin/main          # 6 conflictos: resolver según §4
ruff check . && pytest -q
python -m pip_audit --skip-editable   # en entorno limpio, setuptools>=83
git push -u origin merge/main-into-integration
```
Abrir un PR `merge/main-into-integration` → `integration/hydra-1.0`. Criterios de salida: CI verde en ambos SO y CodeQL sin alertas nuevas.

### Paso C — Consolidar los PRs de seguridad abiertos
1. **#4**: comparar su `hydra/runtime/patching.py` con el rollback que `main` hizo en `coding_loop.py` (#6).
   - Si aporta algo (rollback atómico del propio `PatchTool`, `test_tool_runtime.py`): rebasarlo sobre la integración ya fusionada, añadir `setuptools>=83` antes de auditar y fusionarlo.
   - Si no aporta: cerrarlo.
2. **#1**: cerrar como incluido en #4 y #5.
3. **#2**: cerrar como incluido en #5–#7; sus rutas planas ya no existen tras la integración.

### Paso D — Llevar la integración a `main`
1. Tras el paso B, `main` vuelve a ser ancestro de la integración.
2. Abrir un PR `integration/hydra-1.0` → `main`. Revisión y fusión las hace el titular: la fusión directa sin revisión está bloqueada para el agente.
3. Checks requeridos: `HYDRA CI` (Ubuntu y Windows), `CodeQL`.
4. Fusión recomendada: **merge commit**, que conserva las dos historias; nunca squash, que borraría la trazabilidad commit a commit que usa el ledger de IP.

### Paso E — Después de fusionar
1. Etiqueta `v1.1.0` sobre el merge en `main`.
2. **Protección de `main`**: PR obligatorio, checks requeridos (`HYDRA CI` ×2 y `CodeQL`), sin force-push ni borrado.
3. **Visibilidad**: pasar a privado mientras haya invenciones en revisión (decisión del titular).
4. Cerrar los PRs de Dependabot #10–#12 una vez aplicadas sus versiones (§4, fila 1); Dependabot los regenerará contra la nueva CI si queda algo pendiente.
5. Borrar las ramas ya contenidas en `main`:
   - `hydra-1.0`, `codex/finish-hydra-gguf`, `merge/main-into-integration`;
   - `security/{main-audit-hardening-v2, atomic-patch-rollback, ci-supply-chain-hardening, codeql-analysis, dependabot-maintenance}`;
   - las de #1, #2 y #4 al cerrarlos.

   Antes de borrar `codex/finish-hydra-gguf`, confirmar que ningún agente sigue trabajando en ella.
6. Dejar `integration/hydra-1.0` retirada o como rama de preparación de la 1.2, y trabajar desde `main` por PR.

## 6. Criterios de aceptación

1. `main` contiene la historia de las dos líneas y los PRs #5–#9, sin force-push (`git merge-base --is-ancestor a3ea0eb main`).
2. CI verde en Ubuntu y Windows (Python 3.12), con ruff, tests, `pip-audit`, build y smoke del wheel; CodeQL sin alertas nuevas.
3. `python.test` no ejecuta código en el host; `/hydra/v1/tasks/route` exige token; los parches rechazados se revierten atómicamente. Cada punto con su test en `tests/runtime/`.
4. Cabeceras de copyright al 100 % (`tests/test_license_headers.py`).
5. `main` protegida; decisión de visibilidad tomada; ramas fusionadas borradas.

## 7. Riesgos

| Riesgo | Mitigación |
|---|---|
| Los 9 commits locales se pierden o chocan con otro agente | Publicarlos primero (paso A); comprobar `git status` y el remoto antes de cada paso |
| Resolver mal `tests/test_tools.py` y perder los tests de seguridad de `main` | Fila 6 de §4: comprobar que `tests/runtime/test_tools.py` contiene los tests de fallo cerrado de `python.test` |
| La CI de `main` en 3.11 rompe tras la fusión | Se sustituye por la CI unificada en 3.12 dentro del mismo merge (fila 1) |
| pip-audit rojo por la versión de setuptools del runner | `pip install -U "setuptools>=83"` antes de auditar |
| Squash al fusionar el PR final | Configurar el repositorio para permitir solo merge commits en `main` |
