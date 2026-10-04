<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Hyd: paquete para probas locais

Inclúe o código versionado completo de HYDRA necesario para executar Hyd, configuración, pesos CPU en config/hyd/model.json, calibración, probas e documentación. Non inclúe .env, claves nin corpus xeral en construción. O código conserva compatibilidade histórica; non se inclúen pesos de Kev.

Versión principal: commit c0c84ea, PR #111. Os pesos CPU están dentro do JSON, non nun GGUF. Autoridade desactivada.

Desde unha carpeta nova coa extracción:
    py -3.12 -m venv .venv
    .venv\Scripts\python.exe -m pip install -e .
    .venv\Scripts\python.exe -m hydra.hyd.evaluate --dataset data/human-paraphrase-v1.jsonl --model-dir config/hyd --out resultado-base.json

Para reproducir o adestramento e axuste de temperatura nun directorio distinto:
    .venv\Scripts\python.exe -m hydra.hyd.train --train data/decision-corpus-v3/train.jsonl --calibration data/decision-corpus-v3/calibration.jsonl --out experiments/hyd-proba --epochs 100
    .venv\Scripts\python.exe -m hydra.hyd.evaluate --dataset data/human-paraphrase-v1.jsonl --model-dir experiments/hyd-proba --out resultado-proba.json

Este comando volve adestrar o ranker e axusta a temperatura; non é só recalibración de pesos fixos. min_confidence e min_margin están en calibration.json e podes probar valores na copia. A temperatura está ligada tamén ao modelo: cambiar só o campo de calibration.json provoca un erro de coherencia. Non modifiques os ficheiros orixinais de D:\HYDRA.

O test human-paraphrase-v1 é diagnóstico/regresión, non unha proba independente para promoción. Mantén datos novos separados para avaliar; non uses o test para adestrar. Os corpus incluídos son experimentais, non evidencia de superioridade.

Inclúese tamén o piloto contextual de 30M e a súa base propia en models/. É un experimento anterior: a calibración está vinculada á implementación histórica, polo que non debe cargarse coa implementación principal sen recalibración verificable. A súa implementación histórica está en experimental-code/hyd/. Non hai pesos de Hyd 125M neste paquete.

MANIFEST-HYD.json contén os tamaños e SHA256 dos ficheiros exportados. Non se executaron os checkpoints resume.pt ao empaquetar.
