# Fábrica automática: primeira integración

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Unha orde conecta adestramento, selección do checkpoint, fusión, exportación,
cuantización, arranque local de llama.cpp, execución dos tests precargados,
proba repetida de estabilidade e preparación das respostas para corrixir.

Desde D:\HYDRA:

```powershell
runtime/kev-env/Scripts/python.exe -m hydra.model_factory.finish --bundle config/training/factory-clean-pilot.json
```

O paquete fixa as pegadas da receita, do executable CUDA e de tres suites.
Hai 364 filas antes de eliminar preguntas idénticas. Inclúe preguntas achegadas
polo usuario, regresión de instrucións e exemplos web sintéticos. Son probas
coñecidas: non constitúen unha nova avaliación humana independente.

O resultado queda en models/hydra-program-v1-clean-pilot/human-review-packet.json.
Cada pregunta inclúe a resposta xerada, a referencia e campos baleiros para
human_rating e human_correction. Nunca se copian valoracións doutro modelo.
Un fallo técnico produce TECHNICAL_FAILURE e conserva as respostas obtidas.
O servidor temporal péchase ao terminar ou fallar; Studio non cambia de modelo.
As fases da construción retómanse coa comprobación de pegadas existente;
a avaliación repítese desde o principio, para non mesturar execucións.

READY_FOR_HUMAN_CORRECTION significa que rematou este fluxo técnico.
Non significa precisión suficiente nin aprobación de produción.
A calibración con logits reservados reais do router, a comparación HF/GGUF,
a estabilidade prolongada e a integración das correccións humanas no gate
seguen pendentes. O corpus piloto tampouco é o corpus completo de 24.000 casos.
