<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Changelog de Hyd

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

## 2026-10-04 UTC · HYD-020 · E2 medido con persoas externas (SHADOW_ONLY)
- Que: hydra/hyd/e2_independent.py — acerto de E2 e do Hyd actual sobre preguntas reais de contas que non participaron no adestramento, por persoa e para abstain (P/R/F1). Copias exactas quitadas (nunca borradas), preguntas de molde apartadas da medición, texto tal cal.
- Por que: o test de HYD-019 vén do mesmo grupo que o adestramento; fai falta proba con xente nova.
- Evidencia (experiments/e2-independent-v1/results.json, medido 2026-10-04 16:58 UTC): 3.300 preguntas externas → 54 copias quitadas, 0 coincidencias co adestramento, 980 de molde apartadas → 2.266 medidas. Acerto E2 / Hyd: Juan 1.000 (100 abstain) 69,9 % / 43,6 %; conta nova 1.266 (139 abstain) 53,3 % / 30,8 %; total 60,6 % / 36,5 %. F1 abstain E2 / Hyd: 0,448 / 0,217; 0,549 / 0,182; 0,512 / 0,195. E2 supera a Hyd en todo, pero os dous caen moito respecto do test interno (85,3 % / 71,6 %) → adestrar só coas preguntas dunha persoa non abonda; abstain segue sendo o punto feble (E2 só recoñece o 37 % das abstain de Juan).
- Limitacións: 2 persoas; as de Juan levan «•» e parecen xeradas por IA; cada persoa entende abstain dun xeito distinto; a conta nova non ten chat e reparte mal as clases. 392 preguntas levan número de lista diante; medidas tal cal.

## 2026-10-04 UTC · HYD-021 · E3 especialista de risco, modo observación (SHADOW_ONLY)
- Que: hydra/hyd/e3_risk.py (MiniLM conxelado + cabeza loxística de 5 grupos de risco: abstain, high_risk_review, security, privacy, other; mesmo adestramento e particións conxeladas que E2), hydra/hyd/e3_external.py (medición coas abstain perigosas de persoas externas; lista de palabras DANGER auditable SOLO para escoller as preguntas de proba, nunca entrada do modelo), tests/test_e3_risk.py (6 probas). E3 non decide nada: só observa.
- Por que: as abstain perigosas confúndense con security e high_risk_review; un observador de risco é a peza seguinte do plan MoE.
- Evidencia: no test interno conxelado E3 acerta o grupo de risco no 87,9 % (F1 abstain 0,68). Coas abstain perigosas externas (E3 / E2, experiments/e3-risk-v1/results.json, medido 17:08 UTC): Juan 23 perigosas → vista como abstain 30,4 % / 26,1 %; conta nova 18 → 50 % / 50 %; total 41 → 39 % / 36,6 %. Marcadas nalgún grupo de risco: 92,7 % / 95,1 %. Falsas alarmas (doutras clases marcadas abstain): 15,7 % / 12,2 %.
- Limitacións: 41 preguntas: diferenzas <15 puntos non son concluíntes. A lista DANGER só colle 23 das 100 abstain de Juan. E3 aínda non mellora claramente a E2.

## 2026-10-04 UTC · HYD-022 · Marcas de tipo de abstain e avaliación E3 por tipo (SHADOW_ONLY)
- Que: na app de avaliadores, cada persoa marca as súas propias abstain como «perigosa» ou «falta de contexto» (táboa hyd_abstain_annotations, RLS de propietario, unha marca por pregunta; a pregunta e a etiqueta non cambian). hydra/hyd/e3_annotated.py: precisión, recall e falsas alarmas de E3 e E2 por tipo de abstain e por persoa, con mínimo de 10 marcas por tipo.
- Por que: non depender da lista de palabras para definir «perigosa»; as marcas humanas son o criterio.
- Evidencia: measurements preparadas; 0 marcas na primeira medición (experiments/e3-annotated-v1/results.json) → sen resultados aínda. As marcas chegaban despois (HYD-023).

## 2026-10-04 UTC · HYD-023 · Corrección de marcas de tipo de abstain
- Que: revisadas as 750 marcas de Juan e Belén; 84 corrixidas segundo a guía de abstain (tipo 1 recusar / tipo 2 falta de contexto). Juan: 4 «falta de contexto» → «perigosa» (reseña falsa para afundir un restaurante, texto de superioridade xenética). Belén: 63 «perigosa» → «falta de contexto» (peticións de datos persoais doutras persoas — DNI da profesora, onde vive a veciña —, dilemas morais e preguntas de opinión) e 17 «falta de contexto» → «perigosa» (reseñas falsas, rumores, falsificar notas, mensaxes feitos para ferir, carta de despedimento falsa).
- Por que: as marcas iniciais fixéronse antes de coñecer a guía; deixalas ensinaría ao modelo unha fronteira equivocada entre abstain e high_risk_review.
- Evidencia: marcas finais — Juan 100 perigosas; Belén 280 perigosas e 370 falta de contexto. Ningunha pregunta nin etiqueta de hyd_records modificada nin borrada. Correccións aplicadas vía SQL sobre hyd_abstain_annotations. Pendente: medir E3 por tipo con estas marcas.
- Nota: a copia de traballo local de Hyd perdeuse nesta data; os guións de medición de HYD-020–022 foron reconstruídos a partir das notas de deseño. Os resultados medidos (experiments/*/results.json) son os orixinais desas execucións.
