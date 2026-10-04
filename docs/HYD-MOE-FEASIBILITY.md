<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# MoE para HYDRA/Hyd — análise, 2026-10-03

Estado: deseño experimental, sen modificación da arquitectura activa, sen
adestramento nin xeración de GGUF. A prioridade actual é estabilizar o motor.

Idea reservada por petición do usuario: controlador de memoria que amplíe
gradualmente os bloques adestrables se aumenta a VRAM libre e hai necesidade
de aprendizaxe medida. Se aumenta a ocupación, reducir a carga. Separar
conxelación de pesos de descarga á RAM; preservar o optimizador, aplicar
marxe, histérese e cambios só entre pasos completos. Non implementalo agora:
continuar primeiro co plan inicial do motor Hyd/HYDRA.

## Dúas integracións diferentes

O motor HYDRA xa dispón de selección de modelos, workers especialistas,
critic, judge, cascadas e límites de chamadas. Mellorar esa coordinación
aproveita `scheduler/planner.py`, `registry` e o router existente. É unha
coordinación de especialistas no sistema, non un Transformer MoE por token.
Debe respectar privacidade, dispoñibilidade, capacidades e o orzamento antes
de aceptar unha suxestión aprendida de Hyd.

Nun MoE interno, algunhas FFN do Transformer substitúense por varias FFN e
un router aprendido escolle os expertos para cada token. Non hai garantía
de que un experto se converta en "código" e outro en "galego": hai que medir
a especialización, non impoñer etiquetas ao comportamento emerxente.

## Orzamento calculado para a forma actual

Base densa: vocabulario compartido 32.000, hidden 576, 30 capas, FFN 1.536,
9 cabezas e 3 KV; 124.635.456 parámetros. Cada FFN SwiGLU sen bias ten
3 × 576 × 1.536 = 2.654.208 parámetros.

| Deseño proposto | Parámetros totais | Parámetros activos aproximados por token |
| --- | ---: | ---: |
| Base densa actual | 124.635.456 | 124.635.456 |
| 4 expertos top-1 en 10 capas, FFN 1.536 | 204.284.736 | 124.658.496 |
| 4 expertos top-1 nas 30 capas, FFN reducida a 384 | 124.704.576 | 64.984.896 |

As contas inclúen router linear sen bias por capa MoE. "Activos" é unha
aproximación de parámetros usados, non FLOPs, memoria pico nin velocidade
medida. A segunda variante mantén capacidade FFN activa próxima á base pero
supera 125M totais. A terceira mantén ~125M totais reducindo capacidade por
experto; non se pode supoñer que supere a base densa.

Os pesos e estados do optimizador de todos os expertos ocupan memoria aínda
que só se seleccione un por token. A medición previa de 6,1 GB da receita
densa non vale como medición MoE. Unha implementación inxenua pode ser máis
lenta pola distribución e agrupación dos tokens.

## Experimento recomendado cando se autorice o modelo

Manter primeiro unha base densa como control. Prototipar MoE nunha forma
pequena con top-1, router FP32, balanceamento de carga e regularización da
estabilidade dos logits; probar inicialmente sen descartar tokens e cun
límite estrito de lote/contexto. O deseño definitivo depende das medicións.

Comprobar gradientes só nos expertos seleccionados, serialización e
reanudación, causalidade, ausencia de perda silenciosa de tokens, determinismo
da inferencia e compatibilidade do encoder de decisións. Medir utilización
por experto, colapso, NLL por fonte, memoria e tokens/s na GPU de 8 GB.
Comparar con iguais datos e un orzamento de cómputo explícito. Medir tamén
calibración e decisións de Hyd; unha mellor perda lingüística non certifica
un mellor motor de decisión.

O cargador actual de Hyd usa `LlamaModel`; un checkpoint MoE necesitaría un
encoder compatible propio e metadatos de arquitectura. Non debe cargarse
como se fose a forma densa nin substituír silenciosamente os seus pesos.
O replay e a revisión dos erros poden axudar a unha base densa ou MoE,
pero MoE non resolve por si só o esquecemento nin verifica as etiquetas.

## Fontes primarias

- Switch Transformers: https://arxiv.org/abs/2101.03961
- ST-MoE: Designing Stable and Transferable Sparse Expert Models:
  https://arxiv.org/abs/2202.08906

As fontes documentan sparsity, enrutamento e dificultades de estabilidade.
As dimensións e estimacións desta nota derivan da configuración local de
HYDRA; non son resultados publicados nin medicións do prototipo.
