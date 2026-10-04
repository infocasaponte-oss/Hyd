# Melloras preparadas para desenvolvemento

Código local baseado no ZIP achegado; non despregado en Lovable nin aplicado sobre Supabase. Non precisa créditos de IA para compilar nin pasar as probas.

## Cambios

- Consentimento e versión comprobados no servidor; texto conservado exactamente, sen trim.
- Orixe explícita: petición de usuario, pregunta de avaliador, asistida por IA, sintética ou descoñecida. As preguntas escritas por ti poden empregarse en experimentos; non se presentan como varios avaliadores independentes por usar varias contas.
- Dereitos declarados polo colaborador; non se inventa a autoría nin se completa a verificación para rexistros históricos.
- Exportación da conta por defecto; grupo de contas propias ou corpus global só con configuración de servidor. Sen correos, IDs de conta, notas privadas nin opinións IA no corpus exportado. Reconto total separado dos 500 rexistros visibles.
- Paginación por ID e corte temporal; o resultado declara que non é un snapshot transaccional. A separación/fixación verificable queda no calibrador.
- Conflitos e rexistros de procedencia pendente quedan aparte; a detección de plantilla non cambia a orixe declarada.
- Etiquetas do contrato de HYDRA; revisión opcional por fila nos lotes.
- Corrector inicial de formato e edición humana: mostra orixinal e proposta, require motivo e aceptación; garda variantes separadas. Non fai corrección lingüística automática nin certifica a etiqueta dunha variante. As variantes aínda non se inclúen no export de adestramento.
- Segunda opinión configurable: gateway Lovable ou endpoint local/HTTPS compatible. Permiso separado, timeout, resposta estrita, hashes do prompt/texto e data; gravado condicional para non sobrescribir a opinión xa existente. A confianza é autodeclarada, non unha métrica calibrada.
- OAuth devolve o erro real se falla a creación da sesión de Supabase. As probas usan dobres de servizo, non contas reais.

## Preparar a proba coa túa conta

1. Revisar e aplicar a migración `supabase/migrations/20261004_hyd_development_metadata.sql` na base de desenvolvemento. Antes, preservar unha copia dos datos e inspeccionar as políticas existentes de hyd_records. Non se substitúen políticas descoñecidas nin se alteran textos históricos.
2. Conservar a configuración real do teu proxecto en `.env` local, que queda excluída de Git/paquete. `.env.example` só leva nomes de variables. Para combinar as dúas contas túas, configurar os UUIDs reais en HYD_OWNER_USER_IDS. Para export global, configurar HYD_CORPUS_ADMIN_USER_IDS só coas contas de operador.
3. Regenerar os tipos de Supabase despois da migración e comprobar que coinciden cos tipos aditivos incluídos.
4. `bun install --frozen-lockfile --ignore-scripts`, `bun run test`, `bunx tsc --noEmit`, `bun run build`.
5. Probar entrada por correo e Google, retorno ao dominio permitido, creación/renovación da sesión, peche e conta distinta. Verificar que un fallo de OAuth non aparece como éxito e que non se poden ler/corrixir rexistros alleos desde chamadas directas. Esta proba real queda pendente da sesión/configuración da conta.
6. Probar consentimento ausente en chamada directa (debe fallar), texto con espazos (debe conservarse), lote con etiquetas por fila, variante separada, exportación por conta/grupo e segunda opinión con permiso.

Os rexistros históricos teñen source_kind=unknown e rights_verified=false tras a migración: revisar a súa procedencia, non reetiquetalos automaticamente. O teu CSV de 2936 filas non se inclúe neste paquete. Os 338 duplicados exactos detectados non se borraron da base.

## Conexión co calibrador

Os ficheiros admitidos manteñen text/expected/meta e engaden rights, compatibles co build independente. Os rexistros pendentes teñen excluded_reason. O snapshot humano estrito de HYDRA usa outro esquema, con referencias de consentimento/revisión/person_id: non se afirma que este export xa conteña esa evidencia. Unha migración posterior debe mapear as contas propias a unha persoa e manter a procedencia sen inventala.

Pendentes: aplicar/validar SQL real e RLS, probar OAuth real e envío real ao provedor, revisión de etiquetas das variantes, mapeo autenticado de persoa, historial completo de opinións e snapshots transaccionais. A integración de laboratorio en HYDRA vai na PR #119; o calibrador independente, na PR #1 de Hyd.

## Portabilidade completa

O requisito do propietario é que os datos gardados sexan exportables. Engadido o botón Descargar arquivo completo do ámbito, separado do JSONL filtrado para adestramento. Exporta todos os campos gardados de hyd_records e hyd_question_corrections no ámbito autorizado (conta, grupo propio configurado ou administrador), con paginación, contrato e hash do payload. Non exclúe rexistros pendentes, duplicados, notas nin opinións existentes. Contén datos privados: é unha copia de seguridade, non un corpus para publicar.

Se falta a táboa de correccións ou non se pode ler, falla e non presenta unha copia parcial como completa. A lectura non é un snapshot transaccional. Non recupera historia eliminada nin datos internos non accesibles de Lovable/provedores. O JSON pode verificarse e lerse independentemente; unha restauración na base necesita validar o esquema, propietarios e políticas, e aínda non se implementou importación automática.

17 probas locais pasan, TypeScript e compilación comprobados. Queda probar con datos reais tras aplicar a migración e conectar a conta. Mañá pedir a Lovable tanto o JSONL do corpus como o arquivo completo, e comparar os seus recontos cos da base.
