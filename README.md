# Calibrador independiente de Hyd

Herramienta inicial para preparar corpus, evaluar y calibrar el ranker lineal de Hyd. Funciona sin instalar HYDRA. Requiere Python 3.12 o posterior y NumPy.

```powershell
python -m pip install -e .
python -m hyd_calibrator --help
python -m unittest discover -s tests -v
```

Los modelos incluidos son evidencia histórica; los JSONL de preguntas se conservan localmente y están excluidos de Git. Para reproducirlos, usar los tres JSONL del ZIP `hyd-cambios-2026-10-04.zip` bajo `data/hyd-app-corpus-v1/`. Los datos no se descargan automáticamente.

```powershell
python -m hyd_calibrator report --dataset data/hyd-app-corpus-v1/test.jsonl --model-dir experiments/hyd-app-v1 --out experiments/review/baseline.json
python -m hyd_calibrator calibrate --model experiments/hyd-app-v1/model.json --dataset data/hyd-app-corpus-v1/calibration.jsonl --train-dataset data/hyd-app-corpus-v1/train.jsonl --out experiments/recalibrated --target 0.95 --min-coverage 0.1
python -m hyd_calibrator report --dataset data/hyd-app-corpus-v1/test.jsonl --model-dir experiments/recalibrated --out experiments/review/recalibrated-test.json
```

La calibración conserva los pesos, ajusta temperatura por NLL y selecciona confianza y margen con un objetivo explícito para el límite inferior Wilson del 95 %. Si ninguna combinación cumple, marca `target_met=false` y configura abstención. Los intervalos sobre la partición usada para elegir umbrales son diagnósticos: no prueban por sí mismos el rendimiento futuro. `--train-dataset` verifica el hash de la fuente original y ausencia de solapamiento exacto; omitirlo deja `train_overlap_checked=false`.

El resultado usa `hyd-standalone-calibration/1`, no sustituye directamente la calibración del runtime de Hyd. La compatibilidad con el runtime requiere una integración explícita y validar su implementación. Los informes sobre artefactos históricos comprueban modelo, temperatura y criterios, y declaran `runtime_implementation_verified=false`.

Para nuevos corpus:

```powershell
python -m hyd_calibrator build --corpus export.jsonl --out data/new-corpus
```

Cada fila requiere `text`, `expected`, `meta` con `consent=true`, `real=true`, `suspect_template=false`, y `rights` con `license` no vacía y `verified=true`. Estos son datos declarados por el exportador: el programa valida su estructura, no acredita jurídicamente la licencia. Conserva sus metadatos sin inventar autoría. Rechaza conflictos, duplicados y clases ausentes. Partición estable por texto normalizado, compatible con la original, con hashes de cada archivo en el manifiesto. La separación exacta no garantiza separación semántica ni independencia de evaluadores.

El paquete contiene una copia compatible de las características hash del ranker original. Solo admite `hyd-candidate-ranker/1` con `hyd-hash-words-characters/1`; no admite rankers neuronales. Entrenar los pesos queda fuera de esta herramienta. No se declara mejora de clasificación por ajustar temperatura: el orden de los logits permanece igual.
