<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: ciclo de vida das chamadas shadow

RuntimeExecutor iniciaba unha chamada shadow paralela, pero podía abandonar esa tarefa cando a inferencia principal fallaba ou era cancelada. Un bloque finally cancela o shadow pendente e agarda a súa finalización; tamén recolle excepcións xa producidas para evitar tarefas orfas e excepcións non recuperadas.

Non cambian a resposta autorizada, a selección active/canary, o fallback nin os campos da evidencia. A cancelación da petición non se converte nunha resposta válida. É unha cancelación cooperativa local: non garante deter traballo xa recibido polo servidor de inferencia.

As probas sincronizan ambas chamadas con eventos, provocan erro ou cancelación da principal e comproban que o shadow remata antes de devolver o erro. Continúan pasando as probas de canary, evidencia, bridge, fallback, deadline e contratos HTTP.

Non se reinician servizos nin se modifican modelos. A unificación dos contratos de kernel segue pendente.
