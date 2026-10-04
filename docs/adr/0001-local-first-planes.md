# ADR 0001 — Planos local-first con infraestructura opcional

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

**Estado:** aceptado · **Fecha:** 2026-09-26

## Contexto
HYDRA debe funcionar igual en una estación con una RTX 3060 Ti que en un clúster Kubernetes.

## Decisión
Cada plano (ledger, CAS, World Model, corpus, fabric) tiene una implementación local durable en ficheros
(append-only JSONL, SQLite WAL) como fuente de verdad por defecto, y un esquema PostgreSQL/objetos equivalente
para multi-nodo. El bus (Redis/NATS) es tránsito, nunca fuente de verdad.

## Consecuencias
* Arranque sin dependencias y pruebas deterministas offline.
* Reproducibilidad: versiones de mundo y corpus son offsets de logs.
* Multi-nodo requiere desplegar el perfil CLUSTER y sincronizar mediante el esquema SQL.
