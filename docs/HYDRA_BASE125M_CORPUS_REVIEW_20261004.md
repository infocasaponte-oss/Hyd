<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Revisión do remate de HYDRA Base 125M e das novas fontes

## Evidencia verificada localmente

O log `D:/HYDRA/models/hydra-base-v2-125m/train.log` remata no paso 13.039
con train_loss=3.2117, val_loss=3.404 e val_perplexity=30.09. O informe actualizado
atópase na rama de categorías; a copia na rama principal de traballo aínda dicía
«en curso». Non se modificou o traballo doutras ramas nin os procesos de descarga.

`runtime/base-v2-eval/evaluation.json` confirma BOE 7.18, Python 5.85, Markdown
13.85, libros 40.80, prensa 59.81 e lotes técnicos 19.26. Son 40 documentos por
fonte salvo os lotes técnicos, que teñen 11. A perplexidade final do log usa a
validación do preadestramento; estes valores proceden dunha avaliación por fontes.
Non deben confundirse nin compararse sen documentar tokenizadores e mostras das
bases 30M/125M. A atribución da perda en Python á menor proporción de código é
unha hipótese plausible, non unha conclusión causal demostrada.

As mostras son cinco continuaciós fixas, non unha avaliación xeral de coñecemento.
A narrativa contén repeticións e o código mostrado nin sequera é sintacticamente
válido. A mostra de fotosíntese é incorrecta; isto non proba por si só ausencia
total de coñecemento científico. O informe aínda conserva a frase sobre perda de
validación 3.63 que corresponde a unha etapa anterior: o final é 3.404.

## Recarga real do encoder propio

Recargado dúas veces en CPU o checkpoint final de 125M coa implementación da rama
`feat/hyd-hydra-base-encoder` (commit 41c7722). O cargador comprobou pesos,
tokenizador e configuración fronte aos hashes rexistrados na cabeza. Para tres
preguntas técnicas fixas, a diferenza máxima absoluta de embeddings e
probabilidades foi 0.0. Isto é paridade de recarga, non unha medición de accuracy.
Non se descargaron modelos nin se alterou o ambiente de adestramento.
Evidencia: `evidence/base125m-reload-check-20261004.json`.

Este encoder propio non é o MiniLM externo de E2. A recarga real do MiniLM segue
pendente: non hai aquí un novo artefacto E2 adestrado co contrato endurecido e a
dependencia sentence-transformers non está instalada no ambiente comprobado.
Non se inventou unha revisión para facer pasar a comprobación.

O informe da rama rexistra 65.6% dev e 50.2% humano; nesta revisión non se
reexecutaron esas avaliacións. Corrección desta revisión: o manifest de external-evaluation-v2 indica 300 casos
e 287 únicos, pero ese ficheiro é o test xeral de respostas de HYDRA, non o test
de clasificación que se poida asociar sen máis co 50.2% de Hyd. Non se verificou
aquí o ficheiro exacto empregado nesa cifra de Hyd. Cómpre identificar e ligar
cada avaliación ao seu propio dataset antes de afirmar independencia ou deduplicación. O 89/112 referido na mensaxe
equivale a 79.46%, moi por baixo dunha autorización fiable ao 90/95%.
A calibración gardada tamén mostra que 96/101 acertos (95.05%) teñen límite
Wilson inferior 88.93%; unha accuracy puntual non garante o obxectivo.

## Corpus descargado: inventario observado

Lectura completa dos rexistros dos gzip inventariados; hashes dos ficheiros
conservados. A descarga seguiu avanzando durante a lectura, polo que este é un
inventario non transaccional e non un corpus selado.

| Categoría | Ficheiros | Rexistros | Caracteres | Bytes comprimidos |
|---|---:|---:|---:|---:|
| Ciencia | 2 | 1.805 | 112.599.868 | 34.154.979 |
| Lexislación | 7 | 95.514 | 1.790.957.764 | 283.572.559 |
| Lingua moderna | 89 | 72.693 | 1.898.571.761 | 378.091.792 |

Non se atoparon textos baleiros. Non se executou aínda unha auditoría completa
de duplicados, datos persoais, calidade lingüística ou contaminación destes novos
ficheiros. Non son automaticamente datos admitidos de adestramento.

- Ciencia: 1.805 rexistros en inglés; 1.743 con etiqueta CC-BY sen versión e
  62 public-domain. Conservar evidencia de procedencia e resolver a admisión;
  non afirmar «licenza limpa verificada» a partir da etiqueta do manifest.
- Lexislación: 92.285 rexistros EUR-Lex en castelán e 3.229 de Common Corpus
  en inglés. A adquisición xa contén fontes con marca eu-reuse-2011-833.
- Lingua moderna: 27.761 EUR-Lex, 13.008 BSC legal, 5.957 DGT, 24.895 YouTube,
  461 Common Corpus Spanish e 611 Common Corpus English. A etiqueta de categoría
  non implica idioma nin variedade conversacional.
- O manifest EUR-Lex rexistraba 1.663.921.120 caracteres baixo lingua_moderna:
  aproximadamente o 88% do volume inventariado da categoría é desta fonte legal.
  Corrixir o balance por subdominio antes de ampliar a seguinte base.

O manifest YouTube observado antes do remate da lectura tiña 81 unidades,
24.318 rexistros e 180.490.579 caracteres. A razón 3.9 caracteres/token do plan
darían uns 46M tokens estimados, non tokenizados nin válidos tras filtros.
O tamaño de descarga transferido non foi medido; os bytes comprimidos de saída
non son o tráfico de rede. Non se verificou a previsión de 60GB/100M tokens.

Recomendación: revisar rendemento e diversidade por lotes, cun orzamento explícito
de descarga; non completar 160 ficheiros só por cumprir a cifra. A mostra xa
permite medir diversidade, repeticións, erro de transcrición e tokens útiles.
Non se interrompeu nin reconfigurou a descarga en curso nesta entrega.

## Próximas implementacións/probas

1. Selar un snapshot das novas fontes, contar tokens co tokenizador propio e
   aplicar os filtros e descontaminación antes de actualizar current_tokens.
2. Separar lingua moderna legal/administrativa de conversa/divulgación e esixir
   límites por fonte/idioma; non cubrir ocos conversacionais con textos legais.
3. Revisar os 1.743 rexistros de ciencia coa marca CC-BY sen versión e conservar
   evidencia de orixe. Non ampliar dereitos por inferencia.
4. Avaliar Hyd con test humano deduplicado e referencia confirmada, conservando
   tamén os resultados antigos para trazabilidade.
5. O CLI e3-report xa está implementado nesta entrega: require selección explícita
   de eventos humanos revisados e predicións aliñadas polo hash do texto. Falta
   obter eses ficheiros reais; non hai unha nova métrica E3 calculada.
