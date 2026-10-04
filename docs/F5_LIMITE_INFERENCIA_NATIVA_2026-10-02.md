<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: límite temporal da inferencia nativa

O campo HydraTask.budget.max_seconds non limitaba as chamadas do kernel nativo. A fase de execución agora usa asyncio.timeout cun único límite que abrangue o runtime físico e o fallback lóxico. Un timeout pasa polo tratamento de erros existente: status failed e evento hydra.task.failed, sen resultado completed nin captura terminal exitosa.

O contrato HTTP non cambia: execute_task conserva o erro público 502 de execución. A cancelación é cooperativa sobre as coroutines da chamada; non promete deter traballo xa enviado a un servidor remoto nin tarefas shadow independentes.

Non é aínda un límite temporal de toda a tarefa: planificación, verificación e captura conservan o comportamento anterior. Tampouco resolve os límites de chamadas entre os dous kernels. Estes puntos seguen pendentes para a converxencia funcional.

As probas bloquean a inferencia lóxica e física, verifican cancelación, estado failed, evento e ausencia de commit/outbox terminal. Mantéñense os tests de fallback, runtime físico, captura e contratos conxelados. Non se reinician servizos activos nin se alteran modelos.
