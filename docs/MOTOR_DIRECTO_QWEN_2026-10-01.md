# Primeiro motor HYDRA sobre Qwen

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Obxectivo: completar e validar o motor propio sobre os pesos Qwen axustados. Un modelo desde cero queda para unha fase posterior.

Engadido catálogo config/models.hydra-instruction-v8-llamacpp.yaml e opción --backend llamacpp ao Studio candidato. scripts/start_hydra_direct.ps1 comproba o hash do GGUF v8 e esixe CUDA antes de arrancar en 127.0.0.1:18090. O runtime b11146 descárgase do repositorio oficial ggml-org/llama.cpp e compróbase o digest publicado. Non se substitúe o runtime CPU existente.

Execución tras completar a instalación CUDA:

```powershell
./scripts/start_hydra_direct.ps1
./.venv/Scripts/python.exe -m scripts.run_studio_candidate --version 8 --backend llamacpp --port 18089
```

O endpoint de inferencia é local e usa o protocolo compatible con OpenAI; iso non chama a OpenAI nin require unha API externa. O chat directo será http://127.0.0.1:18089/studio cando o servizo estea arrancado.

Instrución de identidade aclarada no worker: HYDRA é o motor deste proxecto e debe distinguirse da procedencia dos pesos. Non se editaron os pesos para impor unha identidade.

34 probas enfocadas pasan e Ruff pasa. Quedan comparación de inferencia real CUDA, identidade, JSON, consumo e estabilidade; adestramento comparativo das receitas v9; revisión humana e criterios de promoción. O GGUF v8 segue sendo candidato experimental. Non se modificou CeltIA nin se retirou Ollama.

## Proba real

Runtime CUDA instalado con digests verificados; arranque con comprobación CUDA e 99 capas GPU. Inferencia directa en 18090: instrución HYDRA correcta; JSON ok=true correcto; identidade incorrecta, atribúe HYDRA a OpenAI tamén sen Ollama. Evidencia docs/evidence/hydra-direct-smoke.json. Non basta cambiar runtime. Studio directo non arrancou: revisión automática bloqueou o comando Start-Process sen indicar un motivo adicional. O Studio anterior segue sendo a interface dispoñible.
