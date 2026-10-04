<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: orzamento de chamadas do plan lóxico

O executor lóxico conta os pasos MODEL antes de comezar e rexeita plans que excedan max_model_calls. O kernel pasa o límite de HydraTask tanto na execución lóxica directa como no fallback lóxico. Os consumidores antigos de Executor.execute conservan a chamada sen ese argumento opcional.

O rexeitamento ocorre antes de resolver modelos ou realizar inferencia. A política previa de bloqueo de ferramentas e efectos laterais conserva prioridade. Mantéñense o resultado do último paso e a verificación estrutural.

As probas comproban rexeitamento sen chamadas e execución dun plan exactamente no límite, ademais de fallback, runtime físico, deadline e contratos HTTP.

Este non é aínda un contador global: chamadas físicas canary/shadow/fallback non están contabilizadas polo executor lóxico. O reconto agregado e a unificación funcional dos kernels seguen pendentes. Non se modifican servizos activos nin pesos.
