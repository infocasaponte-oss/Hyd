<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Hyd: auditoría de Kev e substitución independente en HYDRA

Data: 2026-10-02. Fonte auditada: `D:\kev-main\kev-main`.
Destino: `D:\HYDRA`. Hyd é o substituto do motor de decisión de Kev;
HYDRA conserva a súa arquitectura. Hyd non é un novo orquestrador.

## Estado e alcance real

Implementouse unha primeira base propia, `hydra.hyd`, que substitúe por defecto
o observador externo no seguinte arranque de HYDRA. Non se reiniciaron servizos
de produción nin se eliminaron os artefactos históricos de Kev.

O modelo incluído é un ranker CPU adestrado desde cero con rexistros propios
de HYDRA para dez clases de enrutamento. Non iguala aínda a comprensión xeral
dos modelos Kev baseados en Qwen. Os tres contratos tipados están implementados,
pero as preguntas fóra do dominio adestrado producen abstención explícita.
Unha API compatible en forma non demostra paridade semántica.

Falta adestrar e avaliar a capacidade xeral, facer unha comparación emparellada
con Kev e certificar a substitución en produción. Non se afirma superioridade
global nin se habilita autoridade aprendida sen esa evidencia.

## Método e cobertura da auditoría

`scripts/audit_decision_source.py` le e calcula SHA-256 de todos os ficheiros
observados, excluíndo `.git`, `.venv`, `node_modules`, `__pycache__` e
`.pytest_cache`. Le íntegros os ficheiros de texto recoñecidos e analiza mediante
AST cada Python: importacións, funcións, clases, firmas, documentación, chamadas
e localizacións. Non importa nin executa o proxecto externo.

Resultado: 3.049 ficheiros, 852.470.852 bytes, 133 ficheiros Python e 1.991
símbolos de función/clase, sen erros de lectura ou sintaxe. O inventario completo
é `docs/evidence/hyd/kev-source-inventory.json`. Os símbolos inclúen métodos e
funcións aniñadas; o seu número non é o número de funcionalidades do produto.

Revisáronse ademais manualmente os contratos, o camiño de inferencia, o
adestramento, a carga de checkpoints, a calibración, o servidor e as integracións
de HYDRA. Os achados seguintes son estáticos: non se executaron todas as probas
de Kev, non se reproduciron todos os estudos nin se validaron os pesos publicados.
Inventariar cada símbolo non equivale a verificar formalmente cada liña.

## Que fai Kev e como o fai

Entrada: un estado (texto ou JSON) e preguntas con instrucións e opcións.
Saída: probabilidades e decisións estruturadas. Non xera texto nin executa
ferramentas; tampouco concede permisos ou controla o sistema operativo.

| Concepto | Funcionamento observado | Fonte principal |
|---|---|---|
| Choice | Distribución sobre nomes de opcións; selección do máximo | `kev/api.py` |
| Noul | Dúas opcións; devolve a probabilidade da verdadeira | `kev/api.py` |
| Score | Opcións ordenadas; esperanza do índice do nivel | `kev/api.py` |
| Backbone | Modelo causal Qwen; úsase a representación oculta, sen decoder de texto | `kev/model.py`, `kev/checkpoint.py` |
| LoRA | Adaptación de proxeccións do backbone con poucos parámetros | `kev/model.py`, `kev/train.py` |
| Pointer head | Proxección da posición de decisión e das fronteiras das opcións; produto escalar escalado | `kev/model.py:205` |
| Estado compartido | Prefixo visible para cada pregunta | `kev/model.py`, `kev/shared_prefix.py` |
| Illamento | Máscara de bloques en atención convencional; filas e estados compartidos en modelos híbridos | `kev/model.py`, `kev/shared_prefix.py` |
| Orde das opcións | A máscara illada opcional e os estudos de permutación miden/corrixen sensibilidade | `kev/model.py`, `kev/train.py` |
| Calibración | Divide logits por temperatura positiva; non cambia a opción máxima | `kev/calibrate.py`, `kev/model.py` |
| Augmentación | Ningunha das anteriores, distractores e permutacións | `kev/data.py`, `kev/train.py` |
| Adestramento completo | Masters fp32, FSDP2, resume e snapshots cando se solicita | `kev/full_ft.py` |
| Avaliación | Accuracy, NLL, Brier, ECE, cobertura selectiva, AURC e bootstrap por rexistro | `kev/metrics.py`, `kev/benchmark.py` |
| Servizo | FastAPI, cola de peticións, thread de inferencia e caché de prefixos | `kev/serve.py` |
| Aceleración | CUDA graphs, kernels fusionados e backend MLX | `kev/cuda_graphs.py`, `kev/fused_qwen35.py`, `kev/mlx_model.py` |

O fluxo principal é: validar contrato → serializar estado e criterios → codificar
tokens e fronteiras → executar backbone → puntuar opcións → softmax/temperatura →
reconstruír resposta tipada. As posicións das ramas reinícianse respecto do estado;
o texto do usuario neutraliza secuencias que poderían forxar delimitadores.

O adestramento materializa as mesmas formas que o servidor e usa perda sobre
opcións. Existen opcións experimentais de regularización e calibración que non
deben interpretarse como receitas de lanzamento: o repositorio documenta estudos
rexeitados e diferenzas entre xeracións de modelos.

## Mapa de módulos e responsabilidades

| Grupo | Módulos | Responsabilidade |
|---|---|---|
| Contrato/modelo | `api`, `model`, `checkpoint`, `device` | Conversión tipada, codificación, máscara, cabeza e carga |
| Inferencia | `serve`, `predictors`, `shared_prefix`, `cuda_graphs`, `mlx_model`, `fused_qwen35` | Serving, caché, batching e precisión |
| Datos | `data`, `suite`, `composition`, `contrastive`, `study_v3`, `transfer_v9` | Fontes públicas, xeradores e particións con hashes |
| Aprendizaxe | `train`, `full_ft`, `anchors` | LoRA/full-weight, optimizador e ancoraxe ao base |
| Avaliación | `benchmark`, `evaluate`, `metrics`, `calibrate`, `compare`, `plot`, `jev` | Métricas, comparacións e baseline externo |
| Estudos | `experiment`, `rounds`, `autoresearch`, `budget` | Plans, regras de admisión, leasing e orzamentos |
| Publicación | `publish`, `mirror`, `modal_app.py` | Hub, snapshots privados e execución remota |
| Superficies | `playground`, `space`, `tools/review`, `skills` | Demos, revisión de rexistros e ferramentas auxiliares |
| Evidencia | `evals`, `runs`, `experiments`, `docs/model-cards` | Particións, procedencia, resultados e configuracións |

Cada función/clase e as súas chamadas están no inventario JSON; deben consultarse
xunto coa fonte, xa que unha chamada detectada non acredita que se execute.

## Conexións e fronteiras

Hugging Face: bases Qwen, datasets públicos, descarga/publicación de checkpoints,
espazo demo e espello privado. Modal: GPU, volumes, secrets e lanzamento de
estudos. Vercel AI Gateway: comparación opcional con Jev mediante worker Node.
GitHub e outros servidores: datasets, ferramentas e wheels/kernels auxiliares.
FastAPI expón `/v1/systemone`, `/v1/models`, `/permute` e `/separate`.

O inventario rexistra hosts e nomes de variables de entorno en código, sen
extraer valores de secrets. Un host en tests ou nun script non implica unha
conexión activa no servizo principal. Non se accederon a contas remotas.

## Achados e consecuencias para Hyd

1. **Kev non é o controlador de HYDRA.** O control está no router/kernel de HYDRA.
   O observador recibe evidencias; a autoridade existente só permite pistas de
   tipo de tarefa. Non hai motivo para reconstruír memoria ou ferramentas.
2. **Dependencia existente concreta.** `providers/decision.py` fala co sidecar
   de loopback; `core/bootstrap.py` crea o observador; `config.py` define alias e
   manifests; scripts históricos cargan un checkout e checkpoints de Kev.
   Hyd substitúe o camiño activo de arranque, mantendo o código histórico como
   compatibilidade explícita con `HYDRA_HYD_ENABLED=false`.
3. **Control e evidencias locais inconsistentes.** O artefacto de promoción de
   `hydra-decision-v4` referencia un calibrador Kev, mentres a súa calibración
   local declara SHADOW_ONLY. Ese estado non serve como certificación de Hyd.
4. **Confianza non é garantía.** A confianza Choice de Kev está normalizada
   respecto da uniforme, e Score emprega dispersión ordinal. Hyd v1 devolve
   `confidence = probabilidade máxima`, ademais de marxe e abstención. É unha
   diferenza semántica que debe adaptarse antes de prometer compatibilidade SDK
   completa. Non mesturar limiares de ambas definicións.
5. **Contexto servido e contexto validado difiren.** Kev admite estados de ata
   65.536 tokens; os checkpoints pequenos publicados tiveron adestramento moito
   máis curto. A admisión non demostra calidade en documentos longos.
6. **Precisión depende do ambiente.** Dtype, GPU e kernels cambian resultados;
   a propia documentación rexistra deriva. Comparar candidatos no mesmo ambiente
   e conservar versións, pesos, calibración e corpus con hash.
7. **Protección opcional no sidecar.** O bearer de Kev depende de `KEV_API_KEY`;
   CORS permite todas as orixes. Non é proba dunha exposición nesta máquina.
   Hyd reutiliza autenticación e rate limits de HYDRA e limita loopback sen chave.
8. **Cola de serving.** `Server.__post_init__` usa unha cola sen maxsize. O batching
   ten límite, pero iso non limita todas as peticións en espera. Hyd v1 evita esa
   cola porque usa inferencia CPU local; a futura versión neuronal precisará
   admisión limitada, backpressure e cancelación.
9. **Custos e cloud.** Modal, mirroring e investigación automatizada son rutas
   separadas. Hyd v1 non chama eses servizos, non descarga modelos e non inicia
   adestramento de pago.
10. **Dereitos e procedencia.** A copia local de Kev declara Apache-2.0; bases,
    datasets e terceiros teñen procedencia propia. Hyd non importou código,
    xeradores, suites, adapters ou pesos de Kev. O código novo foi escrito nesta
    sesión; os datos usados son rexistros xa existentes de HYDRA marcados como
    propios e verificados. Esa marca é evidencia do repositorio, non unha auditoría
    xurídica independente nin unha garantía sobre patentes ou marcas.

## Arquitectura propia implementada

Hyd v1 usa features de palabras, pares de palabras e caracteres con hashing
estable e signos, un encoder normalizado de estado/instrucións e outro de
criterios. Unha matriz bilinear adestrada puntúa cada opción. Non emprega tokens
especiais nin a cabeza pointer de Kev. Non depende de PyTorch, Transformers,
Qwen, Modal ou do checkout externo.

Cada opción obtén o seu logit de maneira independente; softmax normaliza o grupo.
Cambiar a orde non cambia probabilidades; engadir opcións si pode cambiar a
normalización, como é esperable. Preguntas diferentes non comparten activacións
nin modifican unhas ás outras. O estado JSON usa unha serialización estable.

Límites actuais: 50.000 caracteres de estado, 64 preguntas, 255 opcións por
pregunta e 100.000 caracteres totais de preguntas. Son límites distintos dos de
Kev; non se afirma paridade de contexto. Non hai truncamento silencioso.

O controller comproba os hashes do modelo, implementación e calibración antes de
aceptar evidencias. A autoridade aprendida segue deshabilitada. Se unha pista se
habilita no futuro, non elimina os requisitos de ferramentas ou razoamento que
xa detectou HYDRA. Non pode conceder permisos nin executar accións por confianza.

## Execución e integración

O gateway actual engade `POST /v1/systemone` e `GET /v1/hyd/status` usando a
seguridade existente. O descubrimento `/v1/models` do gateway conserva os modos
HYDRA. O servizo opcional Hyd ofrece o seu propio `/v1/models`.

```powershell
.venv/Scripts/python.exe -m hydra.hyd.train --epochs 100
.venv/Scripts/python.exe -m hydra.hyd.evaluate
.venv/Scripts/python.exe -m hydra.hyd.serve --host 127.0.0.1 --port 8009
# Alternativa de arranque: scripts/start_hyd_local.ps1
```

O servicio non arranca automaticamente nesta sesión. O script comproba que o porto
estea libre e non detén o antigo proceso. O paquete inclúe `config/hyd/model.json`
e `calibration.json` para que non dependa dun `models/` ignorado por Git.

O adestrador tipado acepta rexistros propios con `state`, `question`, distribución
`target`, `family`, `split`, `training_allowed` e `rights`. Admite hard labels e
soft targets en Choice/Noul/Score; require separación de familias e de estados
entre train e calibration. Non adapta a temperatura de soft targets empregando
o seu argmax como se fose unha etiqueta certa. Exemplo de execución:

```powershell
.venv/Scripts/python.exe -m hydra.hyd.train_typed --train data/hyd/train.jsonl --calibration data/hyd/calibration.jsonl --out models/hyd-typed-v1
```

Eses ficheiros son unha interface prevista para corpus novos, non un corpus
xeral xa dispoñible. O modelo só acepta como dominio adestrado as preguntas
rexistradas; unha confianza grande nun dominio alleo segue producindo abstención.

## Plan para igualar Kev e melloralo con evidencias

| Etapa | Entrega e criterio de finalización | Estado |
|---|---|---|
| 1. Auditoría | Inventario reproducible, fluxo, dependencias e limitacións documentadas | Feita estaticamente; reprodución dinámica pendente |
| 2. Substitución técnica inicial | Backend Hyd propio, configuración, contratos, endpoint e integración sen imports Kev | Implementada e probada |
| 3. Paridade de interface | Confidence Choice/Score, SDK, usage, permute/separate e contexto acordado | Pendentes as diferenzas documentadas |
| 4. Corpus amplo propio | Decisións binarias, opcións abertas, ordinales, regras, negación, excepcións, datas, táboas e documentos; dereitos e familias verificadas | Pendente |
| 5. Modelo de capacidade xeral | Encoder contextual propio no código; se se utiliza backbone alleo, licencia e revisión verificadas. Adestramento admitido, soft targets e reproducibilidade | Pendente; ranker CPU dispoñible como baseline |
| 6. Calibración independente | Familias novas; ECE/Brier/NLL por tarefa, opcións, idioma e lonxitude; fixar limiares antes do test | Pendente |
| 7. Comparación emparellada | Mesmo estado/preguntas, mesma máquina, versións fixadas, bootstrap por documento e custo/latencia completos | Pendente; Kev local non respondeu no porto 8009 |
| 8. Certificación | Test nunca usado para escoller o candidato; exactitude selectiva con límite Wilson ≥ .90, cobertura ≥ .80 e ECE ≤ .10; regresións de illamento/permisos a cero | Pendente |
| 9. Substitución de produción | Arranque Hyd, clientes actualizados, canary, evidencias e rollback ao checkpoint Hyd anterior; retirar procesos/dependencias Kev cando a paridade estea acreditada | Pendente |

Antes de ampliar o backbone, medir o ranker barato contra a tarefa real: unha
solución máis grande só se xustifica se corrixe fallos relevantes. A capacidade
xeral requirirá comprensión contextual que as features léxicas non ofrecen.

Melloras xa verificables a nivel de mecanismo: implementación propia, ausencia de
sidecar obrigatorio/GPU, illamento e invariancia de orde no ranker, abstención por
dominio e unha única seguridade HYDRA. Superioridade de exactitude, linguaxe,
contexto longo ou custo integral require a comparación da etapa 7.

## Evidencia e límites

As probas novas cobren contrato, tipos, orde, preguntas independentes, empates,
límites, NaN, manipulación do modelo, separación de familias, privacidade local,
ausencia de autoridade, arranque e autenticación. As regresións inclúen API,
kernel, router e bootstrap. `docs/evidence/hyd/validation.json` recolle o resultado.

O 100 % na calibración de 200 rexistros sintéticos non é unha garantía de
produción. O informe `routing-diagnostic.json` mide un corpus previo de HYDRA,
declara `independent_test=false` e non habilita autoridade. Non se usaron estes
resultados para modificar o modelo despois da súa avaliación.

Resultado nese diagnóstico: accuracy total 52 %, cobertura selectiva 18 %,
17 acertos entre 18 aceptados e límite Wilson inferior 0,742. O modelo actual
non pasa o criterio de substitución. `docs/HYD-TRAINING-PLAN.md` concreta os datos,
capacidades e cambios necesarios antes de afirmar que Hyd mellora Kev.
