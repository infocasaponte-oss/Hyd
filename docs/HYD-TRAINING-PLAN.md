<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Que debe aprender Hyd para substituír Kev e melloralo

Data: 2026-10-02. Alcance: mellorar o motor de decisión; reutilizar HYDRA,
sen reconstruír o seu kernel, memoria ou sistema de ferramentas.

## Conclusión baseada na implementación e nas probas

Si, precisa máis adestramento, pero tamén máis capacidade de representación.
O ranker bilinear léxico implementado é un baseline de infraestrutura, non unha
reconstrución da capacidade lingüística de Kev. Adestralo durante máis épocas
coas mesmas frases non soluciona a comprensión de negación, condicións,
instrucións arbitrarias ou documentos longos.

En `data/human-paraphrase-v1.jsonl`, sen modificar o modelo despois de ler este
resultado, mide 52/100 decisións correctas, ECE 0,167 e NLL 1,845. Co limiar 0,95
e marxe 0,1 acepta 18/100, acerta 17/18 e ten límite Wilson inferior 0,742.
Non cumpre cobertura ≥ 0,80 nin límite Wilson ≥ 0,90. A autoridade segue apagada.
O corpus xa existía e non é unha proba independente de promoción.

O 100 % de acerto nas 200 frases sintéticas de calibración non se traslada ás
paráfrases humanas. A temperatura 0,5 axústase a esa distribución estreita.
Hai que cambiar datos e calibración, non baixar o limiar para ocultar o fallo.

## Capacidades que necesitan datos e adestramento

| Prioridade | Capacidade | Exemplos/corpus propio que fai falta | Como probar a mellora |
|---|---|---|---|
| P0 | Seguir a pregunta e os seus criterios | Mesmo estado con preguntas que esixen decisións diferentes; opcións e nomes nunca vistos | Holdout de familias e preguntas; un modelo que só clasifica o texto debe fallar estes controis |
| P0 | Choice xeral con opcións dinámicas | Clases novas, opcións descritas con linguaxe natural, nomes opacos, sinónimos, distractores e ningunha das anteriores | Opcións non vistas en train; accuracy/NLL por cantidade de opcións; marxe entre mellores candidatos |
| P0 | Noul fiable | Afirmacións verdadeiras/falsas, evidencias contraditorias e datos ausentes; soft targets só cando a ambigüidade é real | Brier/NLL binarias e taxa de decisións confiadas equivocadas |
| P0 | Score ordinal | Niveis definidos explicitamente, fronteiras entre niveis, escalas de 2 a N e xuízos humanos revisados | Erro ordinal, Brier/NLL e ranked probability score; non tratar a esperanza como unha etiqueta exacta |
| P0 | Negación e regras compostas | `non`, `e`, `ou`, excepcións, condicionais, precedencia e feitos descoñecidos; xeradores escritos por HYDRA con oráculos | Holdout da estrutura da regra, non só valores novos; comprobar contradicións e ausencia de evidencias |
| P0 | Abstención útil | Datos insuficientes, instrucións contraditorias, dominio alleo, pregunta mal definida e caso sen opción válida | Cobertura selectiva e risco condicionado á aceptación, con limiares fixados en calibration |
| P1 | Comprensión multilingüe | Galego, castelán, inglés e mesturas reais; faltas frecuentes como as dos usuarios; paráfrases humanas revisadas | Familias separadas por idioma/autor; non reutilizar traducións da mesma frase nos dous lados |
| P1 | Datas, cantidades e táboas | Datas absolutas, intervalos, unidades, comparacións, rexistros JSON e relacións entre campos | Oráculos deterministas, probas de fronteira, formatos nunca vistos e datos ausentes |
| P1 | Contexto longo | Documentos propios con evidencias ao inicio, centro e final; información contraditoria ou irrelevante | Buckets de lonxitude, posición da evidencia, latencia e memoria; sen truncamento oculto |
| P1 | Decisións útiles para HYDRA | Clasificación da petición, adecuación dun modelo/capacidade e necesidade de verificación segundo criterios explícitos | Comparación co router actual; a saída non se converte nun permiso nin modifica o kernel |
| P1 | Resistencia a instrucións no estado | Texto que intenta substituír a pregunta ou forzar unha opción; delimitar estado como datos | Corpus adversarial separado; cero ampliación de permisos e correcta interpretación dos criterios |
| P2 | Transferencia entre dominios | Documentos de soporte, código, investigación e clasificación administrativa con dereitos admitidos | Dominios completos retidos; comparar co baseline e con Kev sobre entradas idénticas |
| P2 | Probabilidades máis estables | Variación de opcións, paráfrases, preguntas agrupadas e ruído irrelevante | ECE/Brier/NLL por dominio e tests de invariancia; a estabilidade léxica non garante exactitude |

Necesidade de ferramentas, seguridade e privacidade son clasificacións. Hyd non
aprende a conceder acceso, executar comandos ou saltar autorizacións. Esa
responsabilidade segue nos mecanismos existentes de HYDRA.

## Melloras de código que non se resolven adestrando

1. Completar a compatibilidade de confidence Choice/Score, SDK, usage e endpoints
   de comparación. O contrato actual documenta as diferenzas, non as oculta.
2. Incorporar un encoder contextual máis capaz no backend propio, mantendo
   candidatos separados e estados/preguntas illados. A implementación será propia;
   se usa pesos base existentes de HYDRA, rexistrar licencia, fonte e hash. Non
   usar adapters ou cabezas adestradas por Kev como se fosen creacións de Hyd.
3. Engadir admisión de GPU, batching limitado, timeout/cancelación, caché limitada
   e partición por orzamento antes dun backend neuronal. A caché terá que incluír
   modelo, revisión, pregunta e criterios, e respectar privacidade.
4. Verificar estado/preguntas con esquema JSON, límites e erros estables. Validar
   sumas, NaN, opcións ausentes e tipo de resposta. Non truncar feitos en silencio.
5. Gardar lineage completo: fonte de datos, particións, seed, código, dependencias,
   dtype, dispositivo, checkpoint e calibrador. Un hash de código non captura
   por si só cambios nos kernels ou bibliotecas.
6. Crear un runner de comparación emparellada con bootstrap por documento,
   métricas por familia e latencia/custo totais. As métricas do ranker local
   dispoñibles agora exclúen HTTP, arranque e concorrencia.
7. Engadir un mecanismo de promoción administrado con evidencia íntegra e
   rollback entre revisións Hyd. Non converter a palabra `PROMOTED` nunha proba.

## Orde de execución proposta

**Primeiro: contrato e corpus.** Conxelar o significado de cada resposta,
preparar rexistros xerais propios e revisar os seus targets. O adestrador tipado
xa admite distribucións completas en Choice/Noul/Score e separa familias.
Expandir a admisión de licencias só despois de revisar a procedencia das novas
fontes; hoxe acepta rexistros marcados como propios de HYDRA.

**Segundo: representación e adestramento.** Comparar o ranker CPU cun backend
contextual independente. Entrenar estado+pregunta+criterios, non só unha etiqueta
fixa de intención. Alternar os tres tipos de tarefa; incluír negativos difíciles
e casos de abstención. Manter o corpus de paráfrases xa medido como regresión,
sen usalo para adestrar ou presentalo de novo como test intacto.

**Terceiro: calibración.** Retirar a dependencia de templates repetidos. Reservar
familias novas para calibration e development; calibrar por tipo cando hai
evidencia suficiente. Avaliar soft targets coa súa distribución, non só argmax.
Conxelar limiares e modelo antes de acceder ao test novo.

**Cuarto: comparación e substitución.** Recuperar un baseline Kev fixado e
avaliar ambas versións nas mesmas preguntas. Medir as capacidades da táboa, non
só routing. Promover só cando a cobertura, risco, exactitude, recursos e
compatibilidade cumpran os criterios predeclarados. Ata entón Hyd é unha base
de desenvolvemento sen autoridade aprendida, aínda que xa substitúa tecnicamente
o observador externo no arranque por defecto.

## Criterio para afirmar que Hyd é mellor

Mellora significativa nun benchmark emparellado coa distribución real de HYDRA,
sen regresión nas outras familias, illamento e permisos. Separar claramente:
accuracy total, accuracy nos casos aceptados, cobertura, ECE, Brier, NLL e
latencia/memoria completas. Un 95 % de acerto cun 18 % de cobertura non substitúe
un sistema que debe resolver a maioría das decisións.

O volume necesario dependerá da diversidade e da capacidade do backend; non se
fixa unha cantidade arbitraria de exemplos como garantía. Usar curvas de
aprendizaxe en development para determinar que engadir. O test novo non serve
para elixir receitas. Calquera afirmación de superioridade agarda esa evidencia.
