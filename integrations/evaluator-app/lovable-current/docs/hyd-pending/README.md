# Hyd: integración da PR #1 (estado 2026-10-04)

## Feito no código (aplicado)
- Pregunta gardada byte a byte: sen `.trim()` (validación só rexeita liñas baleiras).
- Servidor esixe `consentAccepted: true` + `consentVersion: "hyd-consent/1"`; sen eles a chamada falla.
- Lotes con etiqueta opcional por fila.
- Segunda opinión IA: escritura condicional (`ai_label IS NULL`), nunca sobrescribe; marcada sen autoridade.
- Exportación por ámbito: «só esta conta» sempre; sen ámbito «todas as contas"; o acceso segue as políticas de propietario anteriores.
- Arquivo completo privado (todos os campos, conta, SHA-256), separado do JSONL filtrado.
- JSONL filtrado: `real: null`, `source_kind: "unknown"`, `rights.verified: false`, `independent_review: false`, sen correos.
- Erros visibles; nada se descarga se a lectura falla.

## Preparado, NON aplicado
- `pending-migration.sql`: columnas de procedencia/consent_version/dereitos declarados, táboa de correccións humanas con RLS e GRANTs, trigger de inmutabilidade. Bloqueada polo permiso «Database migrations». Os rexistros históricos quedarían como `unknown` / `false`.
- Do parche orixinal (`pr1-offline-improvements.patch`) quedan pendentes ata a migración: formularios de procedencia/dereitos, correccións humanas, provedor de opinión configurable.
- Non aplicado: cambio en `src/integrations/lovable/index.ts` (ficheiro autoxerado).

## Non se fixo
- Non se publicou a app. Non se activou ningún modelo. Non se borraron filas.
- O resultado diagnóstico 241/313 (77 %) da PR non substitúe ningún resultado histórico: hashes e execución sen verificar.
