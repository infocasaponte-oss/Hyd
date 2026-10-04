<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5-3: execución nativa e bridge físico

As implementacións pasan aos paquetes canónicos e os módulos anteriores son
aliases da mesma instancia. Os consumidores, incluído o kernel e a API antiga,
usan os imports canónicos.

| Orixe en runtime | Destino |
| --- | --- |
| model_registry | registry.native |
| executor | scheduler.native_executor |
| runtime_events | deploy.events |
| runtime_executor | deploy.executor |
| runtime_bridge | deploy.bridge |
| physical_inference | providers.physical |

O executor conserva o bloqueo de plans de ferramentas/efectos laterais e o
verificador estrutural existente. Non se cambia ao verificador por capas nesta
PR. O rexistro nativo conserva selección local e exclusión de modelos apagados.
O perfil nativo non substitúe o perfil multicriterio da plataforma.

Consérvanse canary, shadow, fallback, circuit breaker, rexistro de evidencia,
eventos seleccionados/failover e validación de endpoints HTTP locais. As
funcións e globais de módulos antigos continúan parcheables nas probas.

## Validación e límites

14 probas de caracterización pasaron antes do cambio: executores, bridge,
inferencia física, fallos, kernels con/sen despregamento e F0. Engádense probas
de identidade dos seis aliases e selección local. Executar ademais contratos
HTTP, seguridade e CI completa.

Estas probas usan modelos simulados e transporte HTTP de proba; non certifican
GGUF ou GPU. Este paso integra a localización e dependencias das implementacións,
non fusiona aínda os dous kernels. A seguinte etapa debe conectar a fachada
de compatibilidade ao kernel canónico conservando captura e transaccións.
Non se cambian servizos activos, CeltIA nin pesos.
