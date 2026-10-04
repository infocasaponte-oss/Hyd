# Melloras da aplicación de avaliadores

Parche revisable do código recibido en hydra-calibrator (1).zip, SHA-256 `ddbeeda717f0f050dcda3305b2a6471553cbcefe2769185aa0f364e7b86bd9cd`. A base local exclúe .env; o parche non inclúe credenciais nin os datos do propietario.

Inclúe consentimento no servidor, texto orixinal inmutable, procedencia explícita, dereitos declarados, correccións separadas, etiquetas por fila, segunda opinión configurable, exportación por ámbito autorizado e arquivo portable de todos os rexistros/correccións/metadatos actualmente gardados. O JSONL filtrado do corpus é distinto da copia completa.

Aplicar sobre o código correspondente ao ZIP orixinal, revisar e resolver cambios posteriores antes de despregar. O parche non é unha migración de datos automática. A migración SQL incluída queda pendente de aplicar e probar na base real.

```powershell
git apply --check offline-improvements.patch
git apply offline-improvements.patch
bun install --frozen-lockfile --ignore-scripts
bun run test
bunx tsc --noEmit
bun run build
```

Verificación local: 17 tests, TypeScript, ESLint dos cambios e build pasan. OAuth, RLS, SQL e o provedor real seguen pendentes ata conectar a conta. Non se afirma que a orde enviada previamente a Lovable garantise xa a exportación completa.

Para a revisión de mañá: pedir JSONL de adestramento e tamén arquivo completo; comprobar recontos, correccións e metadatos, e rexistrar o hash de ambos. O arquivo completo contén datos privados e non se debe subir ao repositorio público.

Instrucións detalladas en IMPLEMENTACION-DESENVOLVEMENTO.md. O backend de adestramento 4B segue pendente; a preparación de arquitectura e as ferramentas de sistema están na PR #119 de HYDRA-SO.
# Libros e carga múltiple (5 de outubro de 2026)

`corpus-books-uploads.patch` incorpora o catálogo de Elejandría, Textos.info,
Open Library e Cervantes, fichas exportables por obra e carga múltiple persistente.
Aplica sobre a copia local do calibrador no commit
`2ef9b281815c65649bb260929e5601296f525e3c`, despois das entregas de corpus/cola
anteriores. A copia local actual xa contén o cambio no commit `68da076`.

Antes de aplicalo noutra copia, executar `git apply --check <ruta-do-patch>`.
A comprobación inversa pasou na copia local modificada. O código require un
servidor local Node con disco persistente, autenticación existente e
`HYD_CORPUS_IMPORT_DIR` (ou a cola local configurada). Non se despregou en Lovable
nin se verificou unha carga autenticada contra a conta real nesta entrega.

Ver `docs/HYD_BOOK_SOURCES_20261005.md` para límites, importación sen sesión web,
revisión por edición e evidencias reais de descubrimento.
