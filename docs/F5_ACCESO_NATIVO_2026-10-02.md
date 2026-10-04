<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# F5: acceso e auditoría da fachada nativa

O control de acceso pasa de hydra.runtime.security a hydra.api.native_access. A emisión de eventos SecurityAudit pasa a hydra.audit.access. A fachada HTTP importa os módulos canónicos; os antigos son aliases do mesmo módulo.

Mantéñense autenticación do gateway, acceso local sen clave só desde loopback, cabeceiras admitidas, comparación de administrador con hmac e esixencia de HYDRA_ADMIN_TOKEN mesmo en loopback. As claves por cliente conservan client_route e as súas restricións. A auditoría segue emitindo os mesmos campos e identidades hash; non se rexistran tokens.

As probas existentes de acceso, APIs de administración, claves de cliente e contratos HTTP son a caracterización funcional. As probas novas comproban que fachada e imports de compatibilidade comparten a implementación.

Non se xeran nin se rotan claves, non se modifican variables de contorno nin servizos activos. Este paso reduce dependencias da fachada: a unificación dos contratos de kernel e o traslado final da API seguen pendentes.

CodeQL sinalou o SHA-256 directo do token administrador usado como identidade de auditoría. Substitúese por un HMAC-SHA-256 co token como clave e o propósito fixo hydra.admin.audit.v1. Non é un verificador de contrasinais: a autenticación segue usando hmac.compare_digest. A identidade dos novos eventos cambia unha vez fronte á anterior e cambia ao rotar o token; os eventos históricos non se reescriben. Non debe empregarse para recuperar credenciais nin para autenticar.
