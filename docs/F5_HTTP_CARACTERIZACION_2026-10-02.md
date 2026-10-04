<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5-1: caracterización HTTP antes de converxer o kernel

As probas novas executan os mesmos contratos no app independente do runtime
e co montador de rutas do gateway. Comproban autenticación antes de executar,
o envelope answer do chat e os argumentos enviados ao modelo, erro seguro 502,
serialización de HydraResult, acceso administrativo ao bucle de código e
rexeitamento do esquema OpenAI no chat antigo.

A ruta de preparación tamén se executa co kernel actual e un almacén temporal:
reábrese a cadea para comprobar identidade da tarefa, trace, os tres eventos,
o resultado de routing e a integridade persistida.

As chamadas ao modelo/kernel son dobres de proba. Non se afirma inferencia
real, validación GPU ou arranque dun proceso uvicorn con estas probas. A
validación do gateway completo, rate limits, route e coding segue nas probas
existentes de integración e seguridade. Non se inicia o worker nestes casos.

Este paso non redirixe ningunha ruta. Establece regresións para a seguinte PR:
integrar o router/planificador mediante adaptadores, mantendo identidade da
tarefa, plans, eventos e políticas. O arranque separado e os efectos reais
persistidos deben caracterizarse adicionalmente antes da súa substitución.
