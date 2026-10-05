<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Rondas de aprendizaje de Hyd y memoria persistente

Implementación del 5 de octubre de 2026. Las personas deciden las etiquetas;
los candidatos se entrenan aparte. Las preguntas originales, sus números y sus
variantes se conservan. La separación de familias evita reutilizar un mismo
escenario para ajustar parámetros y medir generalización.

## Componentes disponibles

- `decision_rounds`: estados persistentes, exclusión de trabajadores concurrentes,
  recuperación tras reinicio, presupuesto diario, revisión, siguiente ronda y ZIP.
- `decision_active_learning`: cola con originales y hashes, eventos de corrección
  humana, rechazo de texto manipulado, duplicados y contaminación entre particiones.
- `decision_candidates`: entrenamiento de la cabeza, selección exclusivamente en
  dev, temperatura en cal_prob, umbral de abstención en cal_policy y test final.
- `decision_finetune`: ajuste opcional de las últimas dos capas de MiniLM durante
  1–5 épocas, selección por pérdida de dev y exportación de un encoder nuevo.
- `decision_challenges`: propuestas sintéticas reproducibles a partir de fit.
  No tienen etiqueta confirmada ni permiso de entrenamiento; comparten la familia
  original y no cuentan como un test independiente. Se generan al completar una ronda.
- `decision_compare`: comparación emparejada con un Kev local real, pesos y
  calibración fijados, métricas de las diez rutas y bootstrap por familias.
- `SQLiteMemoryStore`: memoria semántica, episódica y procedimental persistente,
  namespaces, revocaciones, hashes, JSONL importable y copias SQLite.
- Página de revisión `/hydra/v1/learning/review`: consultas y escrituras protegidas
  por las mismas credenciales administrativas de HYDRA. Las sugerencias son opcionales;
  una sugerencia nunca se guarda como etiqueta sin una acción humana.

## Arranque y rondas

Desde la raíz del checkout, con Python 3.12 y las dependencias del proyecto.
MiniLM necesita además el extra `decision-learning`, un encoder descargado
localmente y su revisión exacta. No se descarga otro modelo de forma implícita.

1. Crear cinco JSONL: `fit`, `dev`, `cal_prob`, `cal_policy`, `test`. Cada fila
   necesita ID, texto, etiqueta de una de las diez rutas, grupo de escenario,
   SHA-256 del texto y `training_allowed` (true solo en fit). El comando `prepare`
   admite el corpus humano v6 con consentimiento y procedencia declarados;
   reserva una persona y divide las otras por familias. Conserva todos los registros.
   Como ese corpus ya se inspeccionó, el resultado es desarrollo, no un nuevo test ciego.
2. Preparar un pool sin etiquetas confirmadas, con procedencia, consentimiento y
   familias. Las heurísticas de privacidad detectan algunos datos personales;
   requieren revisión del responsable y no certifican anonimización.
3. Crear un JSON de configuración con `paths` (las cinco rutas), `pool`, `batch`,
   `min_admitted`, `epochs`, `encoder`, `seed` y `max_candidates_per_day`.
   Ejemplo de encoder léxico: `{"kind":"hash","dims":512}`.
   Para MiniLM: kind=minilm, model=identificador local/cache, revision=SHA de 40
   caracteres, dims=384, device=cpu o cuda, memory=true o false.
4. `python -m hydra.training.decision_rounds --root data/learning/decisor create --round ronda-001 --config ronda.json`
5. `python -m hydra.training.decision_rounds --root data/learning/decisor tick --round ronda-001`
6. Revisar en la página o con `review --round ronda-001 --id ID --label ETIQUETA --reviewer REVISOR`.
   `ambiguous` requiere una nota y permanece fuera del entrenamiento; `discard`
   descarta para esta adquisición, sin borrar el original. Los nombres de revisor
   son una declaración local, no una comprobación externa de identidad.
7. Repetir `tick`. Se entrena cuando todos los casos tienen decisión y se alcanza
   el mínimo de admisiones. Estado final `WAITING_APPROVAL`, autoridad desactivada.
8. `next --round ronda-001 --next-round ronda-002` usa el candidato para adquirir
   la siguiente tanda y acumula las etiquetas admitidas. No vuelve a pedir los textos
   ya encolados en esta fábrica. No activa el candidato en HYDRA.
9. `watch --round ronda-002 --interval 30 --checks 120` permite comprobaciones
   periódicas acotadas. Espera las personas y se detiene al terminar el candidato.
   `--auto-next --round-limit 5` continúa hasta cinco rondas de desarrollo usando
   nuevas revisiones humanas, sin activar candidatos ni volver a adquirir textos.
   No se ha instalado un servicio automático en el equipo.
10. `export --round ronda-001 --out exports/ronda-001.zip` incluye revisiones,
    candidatos, las cinco particiones y pool, estado y manifiesto portable con hashes.
    Contiene datos privados: nunca subirlo automáticamente al repo público.
    El encoder base externo se identifica por revisión; los pesos afinados se
    exportan con la ronda. Las rutas locales pueden necesitar adaptación al restaurar
    en otro equipo; verificar hashes antes de crear una nueva configuración.

Los originales, snapshots y cabezas quedan ligados a los bytes del código y de
los datos. Si cambia una entrada, crear otra ronda; no reutilizar evidencia vieja.
Las propuestas sintéticas no entran automáticamente en el pool ni en los tests.
El botón de la página comprueba admisiones y prepara snapshots. El entrenamiento
lo ejecuta la CLI/worker con el entorno GPU; no mantiene una petición HTTP abierta
ni exige que el servidor web cargue las dependencias de MiniLM.
Una nueva colección humana se reserva antes de inspeccionarla y se mantiene fuera
de los ciclos de selección. La página muestra casos pendientes tras una recarga;
las correcciones de una revisión anterior siguen disponibles mediante CLI.

## GPU existente sin reinstalaciones

`scripts/run_decision_learning.ps1` ejecuta cualquiera de los cuatro módulos con
el Python elegido. Su parámetro opcional `DependencySitePackages` añade al final
dependencias ya instaladas compatibles con Python 3.12, conservando primero las
del entorno GPU. Ejemplo del equipo de desarrollo:

```powershell
.\scripts\run_decision_learning.ps1 -Python D:\hyd-train\.venv\Scripts\python.exe `
  -DependencySitePackages C:\Users\mejil\AppData\Local\Programs\Python\Python312\Lib\site-packages `
  -Module hydra.training.decision_candidates `
  -Arguments @('train','--snapshot','D:\hyd-train-v6\out\continuous-20261005\snapshot-owner',
    '--encoder-spec','D:\hyd-train-v6\out\continuous-20261005\encoder-spec.json',
    '--out','D:\hyd-train-v6\out\continuous-20261005\nuevo-candidato','--epochs','300')
```

Para afinamiento añadir `--fine-tune-epochs`, `1` a Arguments. No sobrescribe la
caché del encoder ni el candidato anterior. Una pasada puede empeorar: no se
seleccionan épocas mirando el test ni se declara una mejora por ejecutar el ajuste.

## Memoria y PostgreSQL

Por defecto, sin PostgreSQL, el bootstrap conserva la memoria en
`data/knowledge-memory.sqlite3`. `HYDRA_MEMORY_BACKEND=memory` permite RAM,
`sqlite` fuerza el modo local; `HYDRA_MEMORY_NAMESPACE` separa instancias.
El namespace debe asignarlo el servidor autorizado; no sustituye controles de
identidad entre usuarios. Recuerdos sin verificar, en conflicto, revocados o de
particiones reservadas no participan en la recuperación cognitiva. La memoria
de prototipos del candidato procede exclusivamente de fit y su mezcla se elige
en dev; el test no se incorpora a esa memoria.

Se verificó la conexión al proyecto Supabase del usuario mediante Session pooler,
TLS y transacción de solo lectura. No se migraron tablas ni se enviaron preguntas.
La credencial quedó cifrada con DPAPI para el usuario de Windows, fuera de Git.
`scripts/probe_postgres.ps1 -CredentialFile RUTA -Python RUTA_PYTHON` vuelve a
comprobarla sin mostrar el secreto. `postgres_probe` también acepta una variable
de entorno temporal `HYDRA_POSTGRES_URL`.

No introducir esa variable globalmente para una simple prueba: el bootstrap
PostgreSQL existente ejecuta `sql/schema.sql`. La activación de ese backend
requiere revisar el esquema, permisos y migración explícitamente; el éxito de
SELECT 1 no demuestra aislamiento ni escritura de memoria.

## Integración y pendientes de validación

### Experimento humano ejecutado

Se conservaron las 5.844 filas del corpus v6. Una persona se reservó para el
test de desarrollo: fit=2.294, dev=296, cal_prob=332, cal_policy=324 y test=2.598.
El SHA del corpus y las métricas agregadas constan en
`docs/evidence/decision-continuous-development-2026-10-05.json`.

| Candidato | Acierto test de desarrollo | Macro F1 (10 rutas) | Recarga | Política de confianza |
|---|---:|---:|---|---|
| MiniLM congelado + cabeza + memoria seleccionada en dev | 50,58 % | 0,5001 | Reproducida | No supera criterio |
| MiniLM afinado 1 época + cabeza + memoria seleccionada en dev | 49,65 % | 0,4877 | Reproducida | No supera criterio |

Una época de ajuste no mejoró el test en este experimento. Los candidatos siguen
en observación; sus parámetros se eligieron en dev y su política falló en cal_policy.
El test ya se había visto en experimentos previos, por lo que no prueba una victoria
independiente. Estas cifras corresponden a esta nueva partición con cuatro grupos
de desarrollo separados; no son directamente comparables con la media LOPO anterior
de 58,68 %. No se retiró ninguna pregunta por ser del propietario o cambiar números.

Verificación local: suites completas HYDRA 1.140 passed / 87 skipped y Hyd 1.240
passed / 87 skipped. Después de separar el worker de entrenamiento de la API y
añadir las pruebas de PostgreSQL, se verificaron nuevamente las pruebas afectadas.
Ruff pasó sobre los módulos y pruebas nuevos. Los tests unitarios usan fixtures
sintéticas para comprobar contratos; no se presentan como métricas del corpus.

### Validación pendiente

`controller_class` reconoce la nueva cabeza como observador local; las cabezas
y calibraciones antiguas conservan su implementación. El contrato portable solo
admite observación sin autoridad y código compartido idéntico. No se ha reemplazado
Kev ni se ha cambiado la configuración activa.

Para decidir sustitución faltan un test humano nuevo reservado, comparación con
Kev y su checkpoint realmente servido, latencias, precisión/cobertura de abstención,
recall de clases críticas y aprobación humana. La comparación de desarrollo no
autoriza promoción. Los casos multimodales y E3 por subtipo necesitan anotaciones
humanas completas, incluidos negativos; un conjunto solo de positivos no permite
medir falsas alarmas. Alcanzar el 90 % sigue siendo un objetivo, no un resultado.
