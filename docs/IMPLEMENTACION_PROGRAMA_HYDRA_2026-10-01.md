# Implementación do programa HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Implementado nesta ronda:

- Preparación reproducible do piloto, conservando filas e hashes parentais. 1049 train, 244 dev, 239 cal e 48 regresión coñecida. O test web separado permanece fóra do adestramento.
- Auditoría de hashes, identificadores, duplicados exactos, cotas e metadatos. Non certifica independencia semántica. Informe de completitude bloqueado: 1580 rexistros sen todos os campos novos; corpus completo non preparado.
- Trainer con max_steps, warmup_steps, clipping e scheduler configurables. Parámetros efectivos, dtype e checkpoint xa se rexistran. Primeira execución fallou antes dos pasos por warmup_ratio eliminado en Transformers 5.17.0; preservada e repetida con 3 pasos de warmup.
- Calibración clasificador con temperature scaling, NLL, Brier e ECE; CLI esixe split cal e hash do artefacto. Aínda non se axustou nin activou un calibrador Kev real nesta ronda.
- Gate de release que falla ante evidencia ausente, métricas non finitas, ausencia de test humano, revisión, rollback ou estabilidade. Nunca aproba automaticamente.
- Avaliación directa llama.cpp gardando respostas crúas, referencia e exact-match diagnóstico, vinculando hashes e camiño do modelo servido. Non usa Ollama. Exact match en respostas semánticas non equivale a revisión humana.

## Comandos

```powershell
.venv/Scripts/python.exe -m scripts.audit_training_program --corpus data/hydra-program-v1-pilot --output docs/evidence/training-program-completeness.json
runtime/kev-env/Scripts/python.exe -m hydra.model_factory.build_hydra --recipe config/recipes/hydra-program-v1-pilot-r2.json
.venv/Scripts/python.exe -m scripts.calibrate_training_program --input logits-reservados.json --output calibrator.json
.venv/Scripts/python.exe -m scripts.check_training_program_release --evidence acceptance.json --output release-gate.json
```

Os dous últimos comandos requiren ficheiros reais co contrato documentado no código; non existen logits-reservados.json nin acceptance.json aprobados. Non executar a preparación do corpus outra vez sobre a mesma carpeta: rexeita sobrescribir.

## Piloto en curso

Base HF v7, sete proxeccións LoRA, LR 1e-4, r16/alpha32, batch1/accum8, secuencia768, 100 pasos, CUDA e BF16 confirmados. É unha execución técnica inicial, non as catro ablacións completas. Entorno: Torch2.8.0+cu128, Transformers5.17.0, PEFT0.21.1, datasets5.0.1, accelerate1.15.0. Difire do entorno de v8: conservar esta variable no informe comparativo.

## Pendentes do plan completo

Recoller e revisar 24000 exemplos variados con procedencia e grupos; corpus Kev6000; ablacións e seeds; datos de preferencias e DPO só se hai mellora; calibración real; benchmarks públicos pinados e tests humanos independentes; estabilidade 2h/24h; canary e rollback. O piloto sintético non permite saltar estas fases. Non se promocionou ningún candidato e CeltIA permanece sen modificacións.

## Final technical pilot result

100 CUDA steps completed; 18464768 trainable parameters; 3733279744 peak allocated bytes; checkpoint100; eval_loss0.1042489. BF16 preserved on merge. GGUF Q5_K_M built with hash e823921ccbe70ba9b929ae461604e0810704eb45abc6e27a9c01947896708b22.

Candidate quarantined: source web fixture accent corruption. Old inputs preserved, corrected copy and new recipe prepared, automatic corruption detection added. The weights require retraining before use. Diagnostic real llama.cpp inference: 24/48 exact matches on known regression; no correct boolean JSON records. 16/16 exact responses on four-family synthetic web fixtures, which does not establish independent generalization. The quarantined server was stopped; Studio retains v8. Full corpus, real calibration, independent human tests and release gates remain pending.
