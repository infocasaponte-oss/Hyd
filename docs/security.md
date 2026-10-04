# Seguridad de HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

## Modelo de amenazas (resumen)
| Amenaza | Control |
|---|---|
| Inyección de instrucciones en documentos/web | Frontera de contenido no confiable (`hydra.governance.boundary`): etiquetado de fuente, detección, neutralización, `<untrusted_data>` |
| Exfiltración de secretos | Secrets Broker (`secret://`), redacción de salidas, Policy Kernel (sensibilidad → solo local), corpus bloquea credenciales |
| Acciones destructivas | Capacidades mínimas por worker, motor de riesgo (D,E,P,F,I), confirmación explícita, simulación previa, sandbox Docker sin red |
| Modelos maliciosos | Supply-chain scanner (opcodes pickle, `auto_map`/código remoto, lista blanca de arquitecturas), firma Ed25519 obligatoria para producción |
| Manipulación de evidencias | Ledger hash-encadenado y firmado (clave fuera del directorio de datos), anclas Merkle, CAS con verificación. Los triggers append-only de `sql/schema.sql` son esquema reservado aún no conectado |
| Fuga entre inquilinos | `TenantRegistry` (modelos, herramientas, presupuesto, residencia), filtros por `tenant_id` en corpus |
| Divulgación prematura de invenciones | Disclosure firewall en la Release Gate |

## Claves privadas
La clave de firma del ledger (Ed25519) y las claves Fernet del Secrets Broker y del vault de IP se
resuelven con `hydra.core.keystore`, en este orden: variable `HYDRA_KEY_<NOMBRE>` (secrets de
contenedor), `HYDRA_KEYS_DIR` (obligatoriamente fuera de `HYDRA_DATA_DIR`) y keyring del SO (Credential
Manager, Keychain o Secret Service; `pip install "hydra-engine[keys]"`). Los ficheros en claro dentro
del directorio de datos son solo un modo heredado: si hay un backend seguro, se migran, se verifican y se
borran. Junto a los datos queda únicamente la clave pública (`keys/hydra-ed25519.pub.pem`), para poder
verificar ledgers y backups. `hydra backup --include-private-keys` exporta también las claves del keyring.

## Pruebas continuas
`hydra redteam` (inyección, secretos, peticiones prohibidas, herramientas peligrosas, JSON malformado,
evidencias en conflicto, contexto gigante, fallo de modelo, OOM de GPU, artefacto corrupto, ledger
manipulado, registro de corpus malicioso). Cada fallo se convierte en caso de regresión y en corpus de fallos.
