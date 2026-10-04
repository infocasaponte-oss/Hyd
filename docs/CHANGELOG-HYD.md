<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# CHANGELOG Hyd

## 2026-10-04 · HYD-018 · Calibrador independente e validación
- Paquete `hyd_calibrator` con build/report/calibrate, sen dependencia de HYDRA.
- Admisión explícita de metadatos, preservación de dereitos, hashes coherentes e métricas de aceptación con marxe e Wilson.
- Temperatura por NLL e limiares só sobre calibration; abstención cando o obxectivo non se cumpre.
- Probas e CI Windows/Linux; reprodución e límites en README.md e docs/REVISION-2026-10-04.md.

Formato: data UTC · HYD-XXX · que · por que · evidencia. Estado: SHADOW_ONLY, autoridade desactivada.

## 2026-10-03 · HYD-015 · Limpeza do corpus da app de avaliadores
- Que: conflitos de etiqueta resoltos (10 coding/reasoning → coding; 50 tool_use/vision → tool_use; 24 chat/coding borradas). Detección de preguntas de molde (mesmas 4 primeiras + 2 últimas palabras, 6 primeiras ou 5 últimas, compartidas con ≥3 outras): exportadas á parte con real=false.
- Por que: adestrar con conflitos ou moldes ensina a dubidar ou a aprender o molde.
- Evidencia: 0 conflitos na base de datos.

## 2026-10-03 · HYD-016 · Exportación JSONL completa
- Que: a exportación lía só 1.000 rexistros (límite da API); agora pagina e quita copias exactas (mesma pregunta normalizada + etiqueta).
- Por que: o ficheiro hyd-real-corpus-2026-10-03.jsonl tiña 643 filas en vez de 2.077.
- Evidencia: recálculo sobre 2.936 rexistros → 2.598 distintas → 2.077 válidas, 10 clases (200–229 cada unha).

## 2026-10-04 · HYD-017 · Proceso reproducible co corpus da app
- Que: hydra/hyd/app_corpus.py (build: valida, conxela partición por SHA-256 70/15/15 e escribe formato Hyd; report: P/R/F1 por clase, ECE, matriz de confusión, cobertura por min_confidence). data/hyd-app-corpus-v1/ (1.449 train / 315 calibration / 313 test). Modelo experiments/hyd-app-v1 adestrado con hydra.hyd.train (80 épocas).
- Por que: medir Hyd con preguntas reais con consentimento, non con corpus sintéticos.
- Evidencia (test conxelado, n=313): Hyd 512×128 accuracy 0,712, macro-F1 0,692, ECE 0,057, T 0,5; con min_confidence 0,95 cobre 30,7 % con 96,9 % de acerto. Peores clases: tool_use F1 0,51, abstain 0,54, high_risk_review 0,61. Liña base de n-gramas máis ricos (kit hyd-train-kit): accuracy 0,898, macro-F1 0,886 → o teito actual é a capacidade das características de Hyd (512 dims), non os datos. human-paraphrase-v1: 0,52 (config/hyd) → 0,44 (hyd-app-v1); son dominios distintos.
- Limitacións: test do mesmo grupo de avaliadores; non é evidencia independente de promoción. Non se substitúe config/hyd.

## 2026-10-04 UTC · HYD-018 · Repositorio privado: código completo e corpus real
- Que: repositorio GitHub pasado a privado; subido o código completo de Hyd (1.220 ficheiros) e data/hyd-app-records/ (2.077 preguntas reais válidas + 521 sospeitosas de molde, separadas).
- Por que: o consentimento cobre adestrar Hyd, non publicar; só se suben con repo privado.
- Evidencia: export directo da BD (2.936 rexistros → 2.598 distintos → 2.077 válidos; 10 clases con ≥200; 0 conflitos). Autor pseudonimizado por user_id. Excluídos: .github/workflows (o permiso de GitHub non inclúe workflows) e models/hydra-base-v0-30m/final/model.safetensors (120 MB, supera o límite de 100 MB de GitHub).

## 2026-10-04 UTC · HYD-019 · E2 semántico adestrado con datos reais (SHADOW_ONLY)
- Que: hydra/hyd/e2_semantic.py — codificador multilingüe conxelado (paraphrase-multilingual-MiniLM-L12-v2, 118M) + cabeza loxística; C e temperatura escollidos só na partición de calibración. Hyd actual readestrado nas mesmas particións (hyd-app-v2).
- Por que: o modelo lineal de hash estaba no seu teito (plan MoE, experto E2).
- Evidencia (313 preguntas reais de proba, particións conxeladas por SHA-256): Hyd actual acerto 0,716 / macro-F1 0,695 / ECE 0,087; E2 acerto 0,853 / macro-F1 0,847 / ECE 0,030. Con confianza ≥0,85: Hyd decide 47,9 % e acerta 91,3 %; E2 decide 61,7 % e acerta 94,8 %. Mesmo grupo de avaliadores → non é evidencia independente. Autoridade desactivada; E2 só observa.
