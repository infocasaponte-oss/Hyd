<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5-2: contratos e adaptadores de planificación nativa

Os contratos publicados pasan a `core.native_contracts`, o router determinista
a `router.native` e o DAG a `scheduler.native`. Os imports antigos son aliases
das mesmas instancias. Os modelos conservan o seu `__module__` histórico para
manter os nomes OpenAPI e a identidade de serialización pública. F0 debe
pasar sen actualizar as súas referencias.

O router canónico ofrece `route_native(task)` e o planificador canónico ofrece
`create_native(task, route)`. Estas entradas delegan no comportamento publicado:
tipo explícito prevalece, capacidades e confianza non cambian, reasoning
conserva o paso de verificación e a dependencia do modelo, coding/research/
tool_use conservan pasos con side_effects=True e as denegacións do executor.

Os consumers do kernel usan os imports canónicos. Este paso non converte
HydraTask en HydraRequest nin o DAG no plan de workers da plataforma: esa
conversión require preservar orzamentos, modelos físicos, eventos e captura.
Non se declara que os dous kernels xa estean fusionados.

## Validación e seguinte paso

27 probas pasaron antes do traslado. As probas adicionais cobren os seis tipos
explícitos, plans, dependencias e identidade dos aliases. Executar tamén
contratos HTTP F0, probas de kernel/executor e CI completa.

O seguinte paso é adaptar executor/bridge sobre estes contratos e integrar
a execución na fachada do kernel canónico. Non cambia o gateway activo,
CeltIA, os pesos ou a autorización de execución de ferramentas.
