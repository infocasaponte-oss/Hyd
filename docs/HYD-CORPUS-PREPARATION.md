<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Preparación do corpus e autorización — 2026-10-03

Orde vixente: continuar a construción e revisión do corpus e preparar o
tokenizador v1; non iniciar preadestramento ata unha orde humana explícita.
`Stage1Plan.pretraining_authorized` é falso por defecto. O lanzador ordinario
non autoriza adestramento. A CLI tampouco admite autorización desde un plan
JSON sen a opción explícita de inicio.

O proceso actual de construción debe rematar e selar o seu manifest. Non se
adestra un tokenizador con shards parciais. Evitar outro escritor nos destinos
`models/hydra-base-tokenizer-v1` e `data/hydra-base-tokens-v1`.

## Control de calidade

`hydra/hyd/corpus_quality.py` percorre todos os documentos, comproba os hashes,
as licenzas admitidas, duplicados exactos e contaminación entre particións por
obra. Usa SQLite para limitar a memoria e publica só contadores, sen copiar
texto nin posibles datos persoais no informe. Sinala caracteres de substitución,
posibles correos e proporción baixa de letras. Os avisos deteñen a preparación
para unha revisión por fonte: código e referencias públicas poden ser lexítimos.
Non equivalen a certificación exhaustiva de privacidade nin de calidade OCR.

Antes de cualificar o corpus como profesional cómpre revisar tamén mostras
estratificadas por fonte, lingua, época e lonxitude, repetición e duplicados
aproximados, contaminación dos benchmarks, distribución dos temas e presenza
de datos persoais. Os cambios producirán unha versión nova con historial de
exclusións e novos hashes, preservando o corpus orixinal e as atribucións.

Tras aprobar a revisión: comparar a cobertura e a eficiencia do tokenizador
por lingua e fonte, comprobar ida e volta e tokens especiais, tokenizar o
corpus selado e calcular tokens e duración exacta estimada. Parar antes do
preadestramento. O corpus aínda en construción non está revisado nin certificado.

O watcher local agarda polo selado. Se hai avisos, remata no estado
`CORPUS_REQUIRES_QUALITY_REVIEW`; non transforma silenciosamente os datos.
Sen avisos e tras preparar os datos, remata en
`PREPARED_AWAITING_PRETRAINING_ORDER`. Hyd non recibe autoridade automática.

## Recuperación da construción

A construción orixinal detívose o 2026-10-03 antes de selar o manifest:
o lector de PleIAs ignoraba o campo `local` para un nome de prensa demasiado
longo. A corrección usa o alias local, comproba SHA e impide rutas que saian
do directorio da fonte. A saída parcial `data/hydra-base-corpus-v1` consérvase.
A reconstrución usa un destino novo `data/hydra-base-corpus-v1-r1`, e o watcher
un plan explícito `runtime/hyd-stage1/recovery-plan.json`. Non hai reanudación
fiable da saída anterior: reconstrúese desde as fontes verificadas, sen
inventar un manifest para shards incompletos. Non se inicia preadestramento.
