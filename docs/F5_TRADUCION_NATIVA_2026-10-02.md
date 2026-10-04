<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: tradución nativa

TranslationService, GlossaryStore e split_text pasan a hydra.edge.native_translation. A API importa a implementación canónica. hydra.runtime.translation segue sendo unha alias do mesmo módulo.

Mantéñense glosarios JSON, límites de entrada e fragmentos, chamadas secuenciais, temperatura cero e límite de tokens. As probas fixan a orde dos fragmentos, o glosario en cada chamada e o rexeitamento previo á inferencia cando se supera o límite.

A tradución da plataforma hydra.edge.translation conserva o seu comportamento. Non se fusionan automaticamente os dous algoritmos de fragmentación: o nativo corta por caracteres e o da plataforma protexe marcadores de código. A converxencia futura precisa un contrato explícito para estes casos.

Non se modifican servizos activos, modelos nin glosarios existentes. O adaptador común dos kernels segue pendente.

## Confinamento dos glosarios

CodeQL detectou rutas dependentes da entrada nos accesos aos ficheiros. Ademais da validación do identificador, resólvense o directorio e o destino con realpath e compróbase o límite do directorio antes de ler ou escribir. Rexeítanse enlaces que apunten fóra da raíz. Esta é unha restrición de seguridade intencionada respecto ao comportamento anterior; os glosarios ordinarios manteñen o mesmo formato. A proba de enlaces execútase onde o sistema permite crealos.
