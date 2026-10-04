<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: kernel nativo compartido

A fachada HTTP do runtime importa HydraKernel desde hydra.core.native_kernel. A máquina de estados nativa vive en hydra.core.native_state. As rutas, a captura terminal, a planificación, o fallback físico e os eventos conservan a implementación anterior.

Os módulos antigos son aliases do mesmo módulo, preservando os imports e os monkeypatches. O kernel nativo xa non importa implementacións de hydra.runtime: usa directamente os módulos canónicos de observabilidade, verificación e captura.

Os contratos HTTP conxelados e as probas de transición, execución, runtime físico, fallback e captura deben pasar sen cambiar snapshots. Non se modifican datos, servizos activos nin pesos.

Continúan existindo dous contratos de kernel: HydraRequest/HydraResponse e HydraTask/HydraResult. Este paso centraliza a implementación nativa, pero non os fusiona. Falta deseñar e validar o adaptador de execución común antes de retirar a fachada compatible.
