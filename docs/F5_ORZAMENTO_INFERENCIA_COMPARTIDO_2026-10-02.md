<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: contador compartido da inferencia nativa

O kernel nativo establece un InferenceBudget mediante ContextVar durante a execución. As chamadas do executor lóxico e do RuntimeExecutor físico reservan unha unidade antes de enviar inferencia. Os shadows herdan o mesmo obxecto de orzamento; peticións distintas teñen contextos separados e restáurase o contexto ao saír.

A principal reserva primeiro. O shadow é opcional e omítese cando non queda capacidade. O fallback físico reserva antes de chamar e antes do bloque que marca fallo de saúde: esgotar orzamento non marca como avariado un modelo que non se chamou. Os intentos fallidos consomen unha unidade e non se devolven; un shadow tamén pode consumir capacidade que logo non estará dispoñible para fallback.

O executor lóxico reserva todos os pasos de modelo do plan de unha vez contra a capacidade que queda no contador compartido, non contra o límite orixinal: se as chamadas físicas ou o shadow xa gastaron parte, o plan rexéitase antes de facer ningunha inferencia. Se un paso falla, as unidades dos pasos que non se chegaron a intentar devólvense; o intento fallido segue consumindo a súa. Se o canary falla e o orzamento esgótase antes do fallback, a evidencia rexistra `primary_error` como descoñecido (`null`), non como fallo, porque a variante activa non se chamou.

As chamadas antigas fóra dun contexto non cambian. Isto abrangue o executor físico canónico e o lóxico usados polo kernel nativo; clientes externos ou bridges personalizados que non pasan por eles non están instrumentados.

O kernel cognitivo da plataforma usa agora o mesmo contador. `BudgetTracker` garda as chamadas de modelo nun `InferenceBudget` e `HydraKernel.run` publícao no ContextVar durante toda a tarefa, así que calquera executor nativo alcanzado desde ela reserva do mesmo orzamento. `ModelInvoker` reserva xusto antes de chamar ao provedor, sen ningún `await` entre a comprobación e a reserva: un par *hedged* xa non pode pasar os dous cunha soa unidade libre. Ao contrario que no kernel nativo, aquí un intento fallido ou cancelado (incluído o perdedor dun *hedge*) devolve a súa unidade: só contan as chamadas con éxito, como antes, e en modo FAST (unha chamada) segue sendo posible reintentar tras un fallo. Mentres a chamada está en curso a unidade permanece reservada, así que un xemelgo concorrente non cabe. `charge_model` sen reserva previa segue contando como antes para os chamadores que non reservan.

As probas comproban principal sen shadow cunha unidade e contador compartido físico/lóxico, mantendo canary, fallo, cancelación, fallback e deadline. Non se reinician servizos nin se modifican pesos.
