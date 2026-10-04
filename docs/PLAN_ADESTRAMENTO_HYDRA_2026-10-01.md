# Plan de adestramento, calibración e certificación de HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Data: 1 de outubro de 2026. Proposta baseada en documentación oficial, artigos orixinais e evidencia local. Os tamaños, parámetros e limiares seguintes son decisións propostas para HYDRA, non garantías dos artigos.

## 1. Obxectivo e estado real

Primeiro produto: motor HYDRA propio, modelo derivado de Qwen 1.5B, Kev como clasificador de decisións e inferencia local CUDA mediante llama.cpp. Unha base preadestrada desde cero queda fóra desta fase. Non se pretende resolver problemas matemáticos abertos nin certificar capacidades xerais cun único porcentaxe.

Equipo confirmado: RTX 3060 Ti, 8 GB VRAM. Studio actual: http://127.0.0.1:18088/studio. Runtime directo: 18090. Non é necesario cambiar a vLLM para mellorar os pesos.

O manifesto v8 contén 969 exemplos train, 228 desenvolvemento, 223 calibración e 48 test coñecido. A evidencia de aceptación rexistra 17/31 no subconxunto automático de desenvolvemento, 6/26 noutro subconxunto reservado, 24/48 en xeración libre e 48/48 coa restrición JSON. As restricións de formato non proban coñecemento nin fidelidade ás fontes. As valoracións humanas do candidato v8 están pendentes.

O corpus web piloto ten 128 exemplos sintéticos de catro familias, diferenciados principalmente por entidades e valores: é unha proba técnica, non diversidade suficiente. Os erros recentes inclúen autoría inventada, idioma incorrecto, copia de chamadas de ferramentas, fontes irrelevantes, rexeitamento dunha busca executada e contexto descartado por tamaño. A resposta determinista sobre autoría resolve unha consulta concreta, non rehabilita os pesos.

**Non existe aínda un corpus completo e validado.** Este documento completa a especificación para construílo; non declara que xa se recolleron, revisaron ou adestraron os datos obxectivo.

## 2. Métodos e runtime

SFT é a primeira etapa: exemplos correctos de tarefa, contexto e resposta; perda só sobre o asistente, fin de quenda supervisado e exemplos non truncados. A documentación de [TRL SFTTrainer](https://huggingface.co/docs/trl/en/sft_trainer) describe estas opcións e o packing. Manter inicialmente o Trainer actual para non cambiar datos, librerías e algoritmo ao mesmo tempo. Probar packing só cunha comprobación de máscaras, illamento entre exemplos e igualdade da avaliación.

[LoRA](https://arxiv.org/abs/2106.09685) permite axustar unha parte dos parámetros mantendo a base conxelada. [QLoRA](https://arxiv.org/abs/2305.14314) permite adestrar adaptadores sobre unha base cuantizada. Non se adestra directamente o GGUF: adéstrase a base HF e o adaptador, fusiónase e despois expórtase. Non confundir QLoRA/NF4 de adestramento con Q5_K_M de distribución.

[DPO](https://arxiv.org/abs/2305.18290) utiliza preferencias entre respostas. Propoñemos unha segunda etapa pequena só cando SFT xa funciona e hai pares revisados; non substitúe ensinar habilidades inexistentes. GRPO/RLVR queda para experimentos posteriores con recompensas verificables, evitando optimizar un xuíz que poida premiar respostas falsas. [TRL GRPO](https://huggingface.co/docs/trl/en/grpo_trainer) é a referencia de implementación; non se instala nesta ronda.

vLLM serve inferencia, adaptadores LoRA e saídas estruturadas; non é o adestrador principal. Consultar [LoRA en vLLM](https://docs.vllm.ai/en/latest/examples/features/lora/) e [structured outputs](https://github.com/vllm-project/vllm/blob/main/docs/features/structured_outputs.md). A documentación actual indica Linux/WSL para Windows; o soporte GGUF segue experimental e require un plugin externo. Para HYDRA manter llama.cpp/GGUF e probar vLLM nun entorno Linux/WSL separado con pesos HF cando se necesite concorrencia. Referencias: [instalación GPU](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/), [GGUF](https://docs.vllm.ai/en/latest/features/quantization/gguf/).

## 3. Corpus HYDRA completo para o alcance inicial

Obxectivo da primeira versión: 24.000 exemplos supervisados: 18.000 train, 2.000 dev, 2.000 cal e 2.000 test novo. Son cotas de construción; empezar por un piloto diverso de 2.000 para medir utilidade antes de ampliar. Non encher cotas repetindo unha plantilla. Mestura inicial por idioma: galego 40%, castelán 45%, inglés 15%; revisar resultados por idioma.

| Familia train | Cota | Contido obrigatorio |
|---|---:|---|
| Conversación e historial | 2.000 | Saúdos, correccións, referencias anteriores, cambio de tema, contexto longo |
| Instrucións e transformacións | 2.500 | Formato literal, orde estable, duplicados, táboas, extracción, restricións combinadas |
| JSON e contratos | 2.000 | Tipos, booleanos, arrays, escaping, Unicode, negativos e peticións ambiguas |
| Fontes e busca web | 3.000 | Responder con citas, fontes insuficientes, contradicións, actualizacións e resultados irrelevantes |
| Matemáticas e razoamento | 2.000 | Cálculo comprobable, unidades, lóxica, distinguir ecuación/teorema/conxectura |
| Código | 2.500 | Funcións completas, reparacións, tests, erros reais, seguridade do código |
| Ferramentas | 1.500 | Elección, argumentos, lectura dos resultados, erros, límites e confirmación de efectos |
| Privacidade, risco e abstención | 1.000 | Datos sensibles, falta de datos, revisión humana, accións irreversibles e negativas xustificadas |
| Idioma e tradución | 1.000 | Galego natural, instrucións multilingües, evitar cambio involuntario ao portugués |
| Identidade e procedencia | 500 | HYDRA/Luis, autoría do motor distinta dos pesos, non inventar empresas, non suplantar ao creador |

Dev, cal e test deben cubrir as dez familias e dificultades baixa/media/alta. Dentro de web: 35% fontes suficientes, 20% falta de soporte, 15% fontes contraditorias, 15% busca/lectura fallidas, 15% ruído e instrucións maliciosas incrustadas. Identificar cada familia semántica; non poñer variacións do mesmo problema en splits distintos. En código separar por solución/familia, en web por documento e entidade, en matemáticas por molde de problema, en conversa por escenario.

Datos públicos candidatos: [UltraChat](https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k) para diálogo, [Tulu 3](https://huggingface.co/datasets/allenai/tulu-3-sft-mixture) para diversidade e [Cabuxa/Alpaca galego](https://arxiv.org/abs/2311.03812) como recurso a inspeccionar. Non importar a mestura enteira sen filtrar identidades, erros, licenzas e solapamentos; as condicións poden variar por compoñente. Estes recursos non están descargados nin aprobados aquí.

Web de adestramento: documentos locais con fonte, data, hash e condicións de uso; contextos con fragmentos de soporte anotados. Gardar fixtures para reproducibilidade; as probas de web viva van separadas, porque os resultados cambian. Non copiar preguntas de benchmarks ao corpus. Non afirmar que ler unha páxina confirma toda a resposta.

Cada rexistro debe conter id, familia, escenario, idioma, dificultade, orixe humana/sintética/mixta, fonte e revisión, dereitos de uso, mensajes, ferramentas esperadas, resposta esperada/rúbrica, spans de soporte, criticidade e hashes. En preferencias engadir chosen/rejected e motivo revisado. Retirar datos privados non autorizados.

Control: deduplicación exacta normalizada e MinHash/n-gramas; revisión de veciños semánticos; comprobar contradicións e citas; validadores de JSON, cálculo e código. Ningún detector garante ausencia universal de contaminación. Rexistrar resultados e revisar os casos límite. Dividir por grupos ANTES de parafrasear. Auditar unha mostra aleatoria estratificada e todos os casos críticos; o test humano novo debe ter avaliación independente e desacordos resoltos. A sinteticidade permanece declarada aínda que unha persoa revise a saída.

Corpus Kev separado: 6.000 decisións, con 4.200 train e 600 en cada dev/cal/test. Cobertura chat/coding/reasoning/research/vision/tool_use, políticas security/privacy/abstain/high_risk_review, entradas mixtas, incompletas e fóra de distribución. Especificar precedencia: as políticas poden limitar unha intención operativa, non son só clases mutuamente excluíntes. Non reutilizar o test coñecido de 100 paráfrasis para selección; gardalo como regresión.

## 4. Pipeline da fábrica

1. **Inventario:** versións e hashes de modelo, tokenizer, plantilla, paquetes, código, corpus e licenzas. Medir baseline Qwen de referencia, v7 e v8 co mesmo protocolo. Non presupor que a cadea v7→v8 é mellor ca unha base limpa.
2. **Corpus:** importar, normalizar, validar, deduplicar, separar por grupos, revisar e conxelar. Manifesto con estado draft/validated, cotas alcanzadas e informes. O pipeline bloquea cotas críticas incumpridas e rexistros sen procedencia.
3. **Preflight:** verificar CUDA, VRAM, parámetros adestrables, plantilla, EOS, máscaras e longitudes reais. Proba dun batch, backward/optim e avaliación; ningunha caída silenciosa a CPU. Empregar unha ventá de mantemento para descargar inferencia e Kev durante o adestramento; restauralos logo.
4. **SFT:** receita pinada, seeds, checkpoint, optimizador, scheduler, estado RNG e métricas. Rexistrar perdas por familia e comprobar updates LoRA. Avaliar log-probabilidades base/adaptador como diagnóstico, non como certificado de calidade.
5. **Selección:** escoller con dev, non co test. Repetir finalistas con tres seeds cando o custo o permita; comparar parellas, regresións e intervalos. Non perseguir só a menor eval_loss.
6. **Preferencias opcionais:** 1.000–3.000 pares corrixidos de erros de dev/train, evitando mesturar cal/test. Proba DPO curta con control SFT. Só conservar se mellora a rúbrica e non degrada as capacidades verificables.
7. **Fusión e exportación:** preservar dtype; manifesto tokenizer/template/adapter; comparar HF base+LoRA contra fusionado. Exportar Q8_0, Q5_K_M e Q4_K_M para medir perda e recursos. Seleccionar formato por evidencia, non por nome.
8. **Calibración:** executar o modelo final e axustar calibradores só co split cal, co runtime, plantilla e cuantización finais. Rexistrar tamén identidade do calibrador. Se cambia calquera destes elementos, comprobar a necesidade de recalibrar.
9. **Test final:** executar unha vez tras conxelar configuración. Arquivar respostas crúas, ferramentas, tempo, erros e votos humanos. Se se mira e se corrixe usando ese test, pasa a regresión; crear novo test para unha nova pretensión de independencia.
10. **Estabilidade e release:** soak, concorrencia, reinicio, rollback e gates. Crear candidato e paquete reproducible; a aprobación de produción require evidencia, non promoción automática por finalizar un job.

Reutilizar train_lora.py, build_hydra.py, comprobación de corpus, avaliación externa e Studio candidato existentes. Engadir módulos de importación por licenza, agrupación semántica, métricas por familia, calibrador de corrección e coordinador de fases. Non declarar que estes módulos xa existen por estar neste plan.

## 5. Receitas iniciais para 8 GB

Piloto SFT 1.5B: secuencia 768 primeiro; 1024/2048 só tras preflight e medición de VRAM. Batch 1, acumulación 8, eval batch 1, gradient checkpointing, máximo 2 épocas iniciais, seed 42, r=16, alpha=32, dropout=0,05. BF16 só se confirmado polo runtime; na alternativa FP16 manter trainables FP32. Warmup proposto 3%, clipping 1,0 e scheduler linear; estes knobs deben incorporarse explicitamente ao trainer, non son todos configurables na implementación actual.

Ablación 2×2 xa preparada: catro proxeccións fronte ás sete q/k/v/o/gate/up/down, LR 2e-5 fronte a 1e-4. Mesmo corpus, orzamento e base. Proba de 300–500 pasos antes de runs completos; elixir por dev e cobertura, sen reutilizar cal para hiperparámetros. Control adicional base limpa fronte a v7 só despois de seleccionar unha receita. Axustar r=8/16/32 nunha segunda ronda se hai evidencia de capacidade insuficiente.

Non garantir que unha GPU de 8 GB adestre un 7B/8B: QLoRA, longitudes curtas e offloading teñen custos e compatibilidade a medir. Escala proposta: 1.5B→3B/4B cun piloto QLoRA; 7B só despois de demostrar encaixe e utilidade. Visión require un modelo multimodal e procesador compatible; este GGUF de texto non gaña visión ao subir un número no catálogo.

## 6. Calibración real

Separar temperatura de xeración (mostraxe) da temperatura de calibración (transforma logits para estimar probabilidades). Un valor de confianza escrito polo LLM non é unha probabilidade comprobada.

Kev: axustar temperature scaling con logits e etiquetas no split cal; comparar isotonic/Platt cando exista soporte suficiente. Informar NLL, Brier, ECE con bins declarados, diagramas de fiabilidade, macro-F1, matriz de confusión e resultados por clase/idioma. A referencia clásica é [On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a). A proposta para HYDRA debe validarse nos seus propios datos.

Respostas xerativas: non converter directamente a probabilidade dun token en probabilidade de verdade. Construír un estimador de corrección con variables dispoñibles: soporte das afirmacións, relevancia das fontes, tests executados, acordo entre candidatos e clasificación da tarefa. Adestralo en train/dev con etiquetas, calibralo en cal e medir en test. Xuíces LLM ou NLI son sinais falibles; non ser o único certificado e non asumir independencia do mesmo modelo que responde.

Selectividade: publicar risco fronte a cobertura. Un 95% entre o 10% de preguntas respondidas non equivale a un sistema que resolve o 95% de todas. Axustar umbral review/abstain en cal e conxelalo. O [conformal language modeling](https://research.google/pubs/conformal-language-modeling/) é unha liña posterior: non garante verdade de cada frase e depende de supostos de distribución.

Políticas deterministas permanecen por riba de Kev. O incremento de autoridade pasa shadow→canary reversible→rutas non críticas; as decisións críticas conservan revisión humana. Nin baixar temperatura nin mellorar ECE substitúe precisión.

## 7. Benchmarks variados

| Área | Suite proposta | Medición |
|---|---|---|
| Instrucións | [IFEval](https://github.com/google-research/google-research/blob/master/instruction_following_eval/README.md) + contratos HYDRA novos | strict/loose por prompt e restrición |
| JSON | 400 contratos privados, incluídos arrays/Unicode/tipos | validez, esquema e contido por separado; libre fronte a grammar |
| Matemáticas | aritmética xerada con solución exacta + GSM8K reservado | resposta numérica/unidades; non puntuación por palabras clave |
| Código | [HumanEval+/MBPP+](https://github.com/evalplus/evalplus) + reparacións HYDRA | pass@1 con tests, timeout e sandbox |
| Coñecemento/razoamento | ARC, HellaSwag e subconxuntos MMLU vía [LM Eval Harness](https://github.com/EleutherAI/lm-evaluation-harness) | accuracy por tarefa; non prometer 90% xeral |
| Comprensión multilingüe | [Belebele](https://huggingface.co/datasets/facebook/belebele) nos idiomas dispoñibles + galego humano propio | comprensión, conservación do idioma e adecuación |
| Web/RAG | 500 preguntas con snapshots, faltas de soporte, ruído e contradicións | retrieval relevance, cobertura, soporte e precisión das citas |
| Conversa | 200 escenarios de varios turnos | correccións, referencias, identidade, saída apropiada |
| Kev | 600 test novos agrupados + regresións coñecidas | macro-F1, risco/cobertura, ECE e cobertura por intención |
| Risco | casos benignos/sensibles/incompletos | falsa negativa, falsa alarma, abstención adecuada |
| Runtime | HF, fusionado, GGUF e gateway | diferenzas, latencia p50/p95, tokens/s, VRAM, erros, cold/warm |
| Visión posterior | suite separada só cun modelo visual real | texto/imaxe, OCR, abstención se non ve |

Usar métricas de fidelidade como apoio; [RAGAS faithfulness](https://github.com/vibrantlabsai/ragas/blob/main/docs/concepts/metrics/available_metrics/faithfulness.md) define consistencia resposta/contexto. Soporte dunha cita e corrección dunha resposta non son o mesmo, como analiza [Correctness is not Faithfulness](https://arxiv.org/abs/2412.18004). Separar métricas, revisar manualmente e non marcar verified=true só por web.read.

Non traducir un benchmark e presentalo como puntuación oficial. Comprobar lingua dispoñible e licenza. Os 48 exemplos e 100 paráfrasis coñecidos son regresión, non test novo. Publicar denominadores, exclusións, intervalos Wilson/bootstrap, versións e prompts. Cache desactivada nas medicións; probar cache aparte. Execución de código só nun sandbox restrinxido, non no equipo directamente.

## 8. Gates propostos de promoción

Os limiares deben fixarse antes do test e están limitados ao alcance de tarefas básicas HYDRA. Non son resultados alcanzados.

- Test independente representativo: accuracy ≥90% nas tarefas obxectivamente puntuables, cun mínimo por familia de 85%; informar intervalo e non presentar a estimación puntual como garantía. Revisión humana ≥90% aceptable nos casos semánticos, votos e desacordos documentados.
- JSON con contrato: ≥99% válido e ≥95% contido correcto; xeración libre avaliada separadamente. Identidade/configuración: 100% nos casos críticos da suite, incluídos intentos de suplantación, sen ocultar a procedencia cando se pregunta.
- Web: ≥95% de citas realmente soportadas e ≥90% relevancia na suite controlada, con resposta honesta cando falla. Non publicar unha ligazón inventada como fonte consultada.
- Kev non crítico: macro-F1 ≥0,90, coverage ≥0,80 e precisión selectiva ≥0,95; ECE ≤0,05 e Brier/NLL sen degradación relevante. Para rutas críticas manter revisión e medir un límite superior do erro cunha mostra suficiente; unha mostra pequena sen fallos non certifica seguridade.
- HF→GGUF: degradación ≤2 puntos porcentuais no agregado e sen fallos críticos novos. Comparar tamén intervalos e por familia.
- Soak: primeiro 2 h, logo 24 h; 1.000 peticións mínimas mesturadas, reinicios e erros de ferramentas; ningún OOM/non-finite, taxa de erro <1% e sen crecemento persistente de memoria. Separar carga de inferencia da de ferramentas e declarar hardware.
- Rollback ensaiado; manifests e calibradores consistentes; avaliación humana vinculada ao hash final. Ningunha promoción se falta unha evidencia obrigatoria.

## 9. Orde de implementación e entregables

P0: consolidar os fixes de contexto/identidade/verificación, medir baseline reproducible e iniciar corpus piloto diverso. Entregables: inventory.json, source-registry.json, corpus manifest, contamination report e rúbricas.

P1: validar datos e preflight; executar as catro ablacións pequenas e seleccionar unha. Entregables: recipes, métricas completas, checkpoint reproducible e comparación por familia. Medir tempo dun piloto antes de estimar duración total; non prometer horas sen medición.

P2: ampliar ao corpus obxectivo validado; SFT finalista; DPO opcional co control. Entregables: modelo HF, adaptador, tokenizer, resultado dev e rexistro de decisión da receita.

P3: recalibrar Kev e o estimador de respostas, cuantizar, comparar e executar test humano novo. Entregables: calibration report, GGUFs, benchmark ledger e votos por hash.

P4: soak e canary limitado, rollback e gate de release. Entregables: HYDRA.gguf seleccionado, motor empaquetado, model card, corpus card, licenzas, acceptance report e guía de operación. Se non supera os gates, permanece candidato e os erros entran no dev da seguinte versión, non no test oculto.

Este plan non executou novos adestramentos, non descargou as mesturas públicas, non completou as cotas e non promocionou ningún modelo. A especificación executable de cotas e gates acompáñase en config/training/hydra-training-program-v1.json.
