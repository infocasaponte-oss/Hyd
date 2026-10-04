# ADR 0002 — Observar → Proponer → Entrenar → Probar → Desplegar

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

**Estado:** aceptado · **Fecha:** 2026-09-26

## Decisión
Ningún aprendizaje modifica producción directamente. El corpus captura en cuarentena; el Training Lab
produce candidatos firmados; la Eval Arena con regression guard y la Promotion Gate (eval offline, shadow,
canary, seguridad, firma, linaje) deciden; HYDRA Lab despliega por canary con rollback automático.
Procedimientos, routers y configuraciones siguen el mismo camino (CANDIDATE → SHADOW → CANARY → ACTIVE).

## Verificación
Invariante I10 de `hydra doctor`.
