<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: fachada HTTP canónica

A implementación da API nativa pasa a hydra.api.native. O gateway monta ese módulo e as métricas acceden á súa outbox. hydra.runtime.api é unha alias do mesmo módulo: uvicorn hydra.runtime.api:app continúa admitido durante a transición. Non se duplica aplicación, kernel, cola nin worker ao importar ambos nomes.

A adaptación do directorio por defecto de WorkspaceManager pasa a hydra.tools.native_workspace. Mantéñense HYDRA_RUNTIME_DIR/workspaces, límites e confinamento das fontes; non se toca a implementación das copias de repositorios.

Consérvanse as rutas públicas, a precedencia das rutas da plataforma, as políticas de acceso e o lifespan. Os modelos HTTP conservan o nome público hydra.runtime.api para que os schemas OpenAPI conxelados non cambien. As anotacións da fachada avalíanse directamente para evitar dependencia dun namespace legado.

As probas comproban snapshots HTTP sen reescribilos, import standalone/gateway coa mesma aplicación e estado e o adaptador de workspaces. A suite completa verifica consumidores e monkeypatches existentes.

Este paso elimina imports de hydra.runtime desde hydra/api. Non fusiona HydraRequest/HydraResponse con HydraTask/HydraResult: segue pendente a converxencia funcional dos kernels. Tampouco retira aínda os aliases nin declara F6b completo. Non se reinician servizos activos nin se alteran pesos.
