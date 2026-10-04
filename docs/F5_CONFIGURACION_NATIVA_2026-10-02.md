<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: configuración nativa canónica

A vista conxelada Settings.from_platform pasa a hydra.core.native_config. hydra.runtime.config é unha alias do mesmo módulo. A fachada importa a mesma instancia settings; non se crean lecturas adicionais de .env nin se alteran prioridades de variables ou valores por defecto.

A fachada usa directamente request_budget, verification.code, observability.spans/operating, governance.rate_limit e tools.oci_sandbox, xa canónicos. Non cambian límites, verificación, sandbox nin observabilidade.

As probas conservan a configuración procedente da plataforma, o alias HYDRA_API_TOKEN, os valores por defecto e os contratos HTTP conxelados. Un proceso novo comproba a identidade da configuración sen as substitucións de rutas dos fixtures.

Non se modifican .env, credenciais, servizos activos nin modelos. Seguen pendentes a converxencia de execución dos kernels e o traslado final da fachada.
