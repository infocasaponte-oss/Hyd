<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Hyd: aprendizaxe continua verificada — 2026-10-03

## Que significa aprender dun erro

Durante o adestramento supervisado xa hai corrección: a función de perda
compara a distribución prevista coa resposta coñecida e o optimizador axusta
os pesos. Isto non demostra comprensión nin garante mellora xeral. Nun corpus
de libros o obxectivo é predicir tokens; un erro de predición non ofrece por si
só a resposta correcta para unha decisión de HYDRA.

O ciclo proposto é: observar → verificar → curar → preparar replay → adestrar
un candidato separado → calibrar → avaliar → promover con evidencia ou descartar.
O modelo en servizo conserva pesos fixos mentres se prepara o seguinte candidato.
Non se inicia preadestramento sen a orde humana vixente.

## Primeira peza implementada

`hydra/hyd/self_learning.py` prepara unha rolda local versionada, non adestra.
Reproduce os exemplos co xerador propio e comproba os hashes de todas as
particións: un campo `verified=true`, unha resposta do modelo ou unha etiqueta
declarada non son evidencia suficiente. Só mina erros na partición train.
Non usa calibration, development nin test para seleccionar exemplos difíciles.

Reutiliza o detector de privacidade de HYDRA e exclúe os rexistros sinalados
do adestramento. Os avisos heurísticos poden ser falsos positivos nos datos
sintéticos; non se desactiva o detector por iso. Os informes só inclúen tipos
e contadores, non os fragmentos potencialmente sensibles.

Conserva os exemplos train admitidos e engade unha copia de erros, distribuída
por dominio e limitada como máximo á metade do número de exemplos orixinais.
Isto é reponderación controlada, non diversidade nova. As outras particións
consérvanse byte por byte. O manifest fixa fonte, xerador, motor de minería,
modelo, exemplos, exclusións e hashes. Unha rolda existente nunca se sobrescribe.

Primeira rolda: `data/hyd-self-learning-round-001/manifest.json`.
Motor analizado: baseline CPU de routing, non o futuro contextual 125M.
2.320 exemplos admitidos; 1.247 erros; 300 copias adicionais; 80 rexistros
sinalados polo detector de privacidade; total train 2.620. Son diagnósticos
sobre tarefas sintéticas fóra do dominio orixinal do baseline, non un benchmark
independente nin proba de superioridade. Non se modificaron pesos nin autoridade.

## Integración seguinte

HYDRA xa captura parches verificados mediante `hydra/corpus/patch_capture.py`,
con artefactos, dereitos e privacidade. Un test de código aprobado non é unha
etiqueta automática de routing. O adaptador para experiencias reais deberá
relacionar decisión, contexto autorizado e resultado comprobado; manter en
corentena os casos ambiguos, puntuacións sen corrección e evidencias incompletas.
Ese adaptador xeral aínda non está implementado.

O seguinte adestrador reutilizará `train_neural.py`, os checkpoints reanudables
e o bloqueo de GPU do pipeline. Cada rolda terá límite de tempo, exemplos,
épocas e memoria; a perda de development poderá deter unha rolda que empeore.
Non debe editar o seu propio verificador, corpus de avaliación nin condicións
de promoción. Primeiro cómpre obter e avaliar a base contextual propia.

Comparar candidato e versión anterior nas mesmas tarefas: erros por familia,
NLL/Brier, calibración, cobertura e risco, permisos, latencia e memoria. Usar
exemplos anteriores para medir esquecemento e un test independente reservado
para a decisión final. Evitar reusar continuamente un único test como criterio
de optimización: tamén se pode sobreaxustar ao avaliador. Versionar a promoción
e conservar a versión previa para rollback. Ningunha rolda garante mellora.

## Fundamentación

A autocorrección sen feedback fiable pode fallar ou empeorar resultados:
https://arxiv.org/abs/2310.01798 . A crítica con ferramentas ofrece feedback
externo comprobable: https://arxiv.org/abs/2305.11738 . O replay é unha técnica
para mitigar, non eliminar automaticamente, o esquecemento:
https://arxiv.org/abs/2007.00487 . Estes traballos sustentan o deseño; non
constitúen unha avaliación de Hyd.
