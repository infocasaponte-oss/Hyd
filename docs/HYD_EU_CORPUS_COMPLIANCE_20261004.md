# Revisión UE do corpus — 4 de outubro de 2026

Esta entrega prepara evidencia e controis técnicos; non certifica a licitude de
cada obra nin garante ausencia de reclamacións. O corpus novo segue sen autorización
de adestramento. Antes da publicación dun modelo hai que pechar as revisións de
dereitos, privacidade e alcance regulatorio, con asesoramento especializado cando
non exista unha base clara.

## Marco confirmado nas fontes oficiais

O [artigo 53](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-53)
esixe aos provedores GPAI afectados documentación técnica, información para
integradores, política de copyright e resumo público do contido de adestramento
segundo a plantilla da Oficina de IA. A excepción de código aberto dos apartados
1(a)/(b) non elimina 1(c)/(d). Publicar un resumo non concede dereitos sobre as obras.

A [Comisión explica o alcance de desenvolvemento e posta no mercado](https://digital-strategy.ec.europa.eu/en/faqs/general-purpose-ai-models-ai-act-questions-answers):
o artigo 2(8) prevé unha exclusión xeral para investigación, probas e desenvolvemento
anteriores á posta no mercado ou en servizo, con matices para obrigas relacionadas
co desenvolvemento de modelos destinados ao mercado. «Non cobrar» non basta para
resolver o alcance. Hyd, clasificador especializado, e unha base xerativa HYDRA
necesitan análises separadas; o número de parámetros por si só non decide a categoría.

A [plantilla oficial e nota explicativa](https://digital-strategy.ec.europa.eu/en/library/explanatory-notice-and-template-public-summary-training-content-general-purpose-ai-models)
teñen tres bloques: información xeral, fontes e tratamento. O PDF revisado pide
identificar os conxuntos públicos grandes (máis do 3% por modalidade dentro desa
categoría). Non basta unha lista xenérica «web/libros». Para crawling existen
detalles sobre rastrexadores, períodos e dominios. A protección dos segredos
comerciais non suprime esas esixencias. A plantilla é obrigatoria para o resumo;
o [Código de Prácticas](https://digital-strategy.ec.europa.eu/en/policies/contents-code-gpai)
é unha vía voluntaria de demostrar cumprimento doutras obrigas.

A [Directiva 2019/790](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=celex%3A32019L0790)
e o [artigo 67 español, texto consolidado](https://www.boe.es/eli/es/rdl/2021/11/02/24/con#a67)
requiren acceso lexítimo para a excepción xeral de minería e atender as reservas
de dereitos pertinentes. Non se presume que unha persoa en desenvolvemento sexa
unha organización de investigación cualificada para a excepción específica.
Un feed RSS, un repositorio accesible ou ausencia de paywall non conceden permiso
de reutilización por si sós. Un control de robots.txt illado tampouco acredita toda
a revisión das reservas, contratos e dereitos do contido dun dataset intermediado.

Para textos oficiais españois, o [artigo 13 da LPI](https://www.boe.es/buscar/act.php?id=BOE-A-1996-8930#a13)
exclúe certas normas, resolucións e textos oficiais da propiedade intelectual.
Isto non converte todo un portal administrativo en material libre de condicións:
a [Lei 37/2007](https://www.boe.es/buscar/act.php?id=BOE-A-2007-19814)
mantén límites sobre terceiros e datos persoais. «Dominio público» tamén require
verificar territorio, autoría, tradución e edición cando corresponda; unha etiqueta
nunha colección estadounidense non acredita automaticamente a situación en España.

O [RGPD](https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:32016R0679)
esixe base xurídica, finalidade e minimización, entre outras condicións; especial
atención a categorías especiais e datos penais. O [CEPD, ditame 28/2024](https://www.edpb.europa.eu/documents/opinion-of-the-board-art-64/opinion-282024-on-certain-data-protection-aspects-related-to_en)
explica que nin a anonimidade dun modelo nin o interese lexítimo se presumen.
Un correo detectado por regex é unha alerta; a ausencia desa alerta non acredita
anonimización. Non publicar correos, transcricións ou outros identificadores no resumo.

## Achados das fontes descargadas

As fichas gardáronse **na revisión Git exacta dos manifests de descarga**, con
URL, data de captura, bytes e SHA-256. Son declaracións dos distribuidores;
non substitúen os dereitos dos titulares orixinais.

| Fonte | Evidencia observada | Pendentes antes de usar |
| --- | --- | --- |
| [EUR-Lex vía joelniklaus](https://huggingface.co/datasets/joelniklaus/eurlex_resources) | Ficha CC-BY-4.0; descarga etiquetada eu-reuse-2011-833 | Delimitar condicións do dataset e dos documentos; atribución, terceiros e privacidade. Non estender unha decisión sobre documentos da Comisión a todo contido europeo por defecto. |
| [YouTube Commons](https://huggingface.co/datasets/PleIAs/YouTube-Commons) | Ficha CC-BY-4.0; descarga etiquetada CC-BY-3.0; atribución individual requirida | Resolver condicións do conxunto e vídeos/transcricións, autor/canle, título dispoñible e reservas relevantes. Non sobrescribir a declaración orixinal nin inferir autorización. |
| [BSC legal](https://huggingface.co/datasets/BSC-LT/Legal_Catalan_Spanish_Parallel_Corpus) | CC-BY-4.0; ficha avisa de posibles datos persoais/sensibles e falta de anonimización específica | Revisión RGPD e condicións da fonte administrativa. Mantense separado sen admisión. |
| [DGT vía OPUS](https://huggingface.co/datasets/Helsinki-NLP/opus_dgt) | Condicións DGT-TM/Decisión 2011/833 | Preservar versión, fonte, data de actualización e propiedade da Comisión. Reconstruír procedencia sen inventar documento orixinal. |
| [Common Corpus](https://huggingface.co/datasets/PleIAs/common_corpus) | Mestura de fontes e declaracións de licenza; rexistros locais sen URL e algúns CC-BY sen versión | Identificar obra/subfonte, versión e aviso; non aprobar a mestura pola licenza da ficha global. |

As [condicións DGT oficiais](https://joint-research-centre.ec.europa.eu/language-technology-resources/dgt-translation-memory_en#conditions)
inclúen identificación da fonte, última actualización e titularidade da Comisión.
A [Decisión 2011/833](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32011D0833)
ten un ámbito e exclusións que hai que contrastar co contido concreto.

A explicación anterior da allowlist dicía que share-alike obrigaba sempre a
licenciar os pesos igual. Corrixiuse: a relación entre datos, derivados e pesos
non se resolve así universalmente. Mantense a exclusión conservadora do proxecto,
sen cambiar silenciosamente as licenzas admitidas. A aceptación dunha etiqueta
non acredita acceso lícito, atribución ou cumprimento do RGPD.

## Ferramentas e operación real

`corpus-census` verifica os hashes dun snapshot selado e conta os textos completos
co `tokenizer.model` propio, vocabulario 32.000, SHA-256
`edd79f7825e7574771c7d15e71cfa0178794ee67462d398d7cbd4b133c91d8f9`.
Non usa a aproximación caracteres/token. Separa tokens de contido, escenario só
EOS e receita BOS+EOS por documento de `base_pretrain._write`; non fai truncación.
Conta candidatos, duplicados e revisión por separado. O reconto non admite datos.

`provenance-overlay` recuperou **28.497 localizadores explícitos**: 26.083 de
`original.video_link` e 2.414 identificadores de Common Corpus que xa conteñen
unha URL HTTP(S). Un identificador URL segue sen verificar como obra orixinal.
O ficheiro lateral conserva texto, orixinais, hashes e clasificación previa.
Non converte IDs sen URL en enlaces nin inventa autoría ou licenzas. Eses rexistros
seguen pendentes de revisión; o overlay non promove automaticamente ningunha fila.

`corpus-readiness` require o reconto completo e unha revisión vinculada ao snapshot.
Comproba declaracións humanas, existencia/hashes da evidencia e os pendentes de
acceso, dereitos, atribución, reservas TDM, privacidade, idioma, diversidade e
descontaminación. É un diagnóstico previo á construción do dataset; non substitúe
os controis do adestrador nin concede autorización. `training_allowed` queda falso.

A tokenización de documentos grandes normaliza unha vez e conta spans de palabras
co mesmo vocabulario, IDs e puntuacións. A equivalencia da secuencia completa foi
comprobada en 400 rexistros reais, dos cales 200 superan 20.000 caracteres. Unha
palabra ou secuencia de espazos demasiado grande queda **sen medir**, identificada
polo hash, en vez de atribuír cero tokens válidos ou truncar silenciosamente.
`scripts/locate_tokenization_budget_records.py` localiza estes casos sen crear
arrays de tokens do documento completo; non borra nin modifica os textos.

`scripts/build_training_disclosure_draft.py` tamén xerou unha ficha interna do
adestramento 125M xa realizado: comproba a ligazón entre manifests de corpus/tokens/
execución e os hashes reais de pesos e tokenizador. Rexistra seis fontes e
854.523.904 tokens vistos segundo a execución, distintos do volume adquirido agora.
Non rehasha os shards históricos nin os binarios de tokens; non afirma unha
auditoría completa daqueles datos. A identidade do provedor, identificación de
dataset/licenzas e revisión legal seguen pendentes. É un borrador de apoio, non
a plantilla oficial cuberta nin publicada.

```powershell
python -m hyd_calibrator corpus-census --snapshot <snapshot-selado> --tokenizer <tokenizer.model> --out <reconto-novo> --threads 2
python -m hyd_calibrator provenance-overlay --snapshot <snapshot-selado> --out <overlay-novo>
python -m hyd_calibrator corpus-readiness --census <reconto/report.json> --rights <reconto/source-rights-review.json> --evidence-root <evidencias> --out <readiness.json>
```

## Antes do seguinte adestramento e da publicación

1. Resolver os achados por fonte e conservar o rexistro da decisión humana,
   o seu alcance, a evidencia e os hashes. Se non hai base, excluír do dataset.
2. Aplicar filtrado de contido/privacidade, atribución e descontaminación contra
   probas humanas, desenvolvemento, calibración e benchmarks. Manter obras e persoas
   nas súas particións. Non inventar etiquetas Hyd a partir de textos de preadestramento.
3. Revisar o balance por **tokens e rexistro**, non só nomes de categorías: a etiqueta
   lingua_moderna contén moito material lexislativo. Aprobación de idioma e calidade
   conversacional require mostra revisada, non unha conta automática de palabras.
4. Crear un dataset novo admitido e recontalo tras os filtros. Non substituír o
   reconto de adquisición polo de tokens realmente usados nin alterar o test para
   conseguir o 90%. Gardar manifests de splits, tokenizador, código e pesos.
5. Cubrir a plantilla oficial cos datos **realmente usados por cada modelo/versión**,
   revisar o texto e publicalo cando corresponda. O corpus adquirido despois do
   adestramento 125M non describe retroactivamente ese adestramento. O resumo da base
   125M necesita o manifest da súa execución e a cadea de fontes anterior.
6. Preparar política de copyright, contacto de titulares, reclamacións/retirada,
   rexistro de incidencias e avaliación de alcance GPAI/uso en servizo. Non se afirma
   que eses procedementos xa estean despregados ou que a revisión legal rematase.

## Resultado de adquisición — snapshot do 4 de outubro, reconto do día 5

O snapshot selado contén 171.200 rexistros; non inclúe todas as descargas que
continúan despois de selalo. Os seus **115.971 candidatos proceden todos de EUR-Lex**:
89.092 declaran lexislación e 26.879 lingua moderna, pero cambiar a categoría non
converte textos legais en conversa contemporánea. EUR-Lex tamén representa preto
do 90% dos caracteres brutos de todas as fontes. Este material non está equilibrado
para un modelo xeral nin acredita a diversidade necesaria para Hyd.

Nos 115.970 candidatos medidos hai **721.385.900 tokens de contido** e
721.617.840 coa receita BOS+EOS por documento. Un candidato de 246.824 caracteres
queda sen medir por superar o límite seguro dunha palabra/secuencia normalizada;
o seu hash figura no diagnóstico. Non é un documento de cero tokens válidos.
Hai que excluílo dun dataset novo ou revisar o preprocesamento e recontar antes
de usalo. O reconto completo da adquisición segue marcado como incompleto en tokens.

| Partición preservada | Rexistros | Tokens de contido medidos |
| --- | ---: | ---: |
| Candidatos pendentes | 115.971 (un sen medir) | 721.385.900 |
| Duplicados | 4.073 | 25.711.818 |
| Revisión | 51.156 | 110.576.951 |

Detectáronse 728 URLs con identificadores de recheo como `CELEX:None`,
1.743 declaracións CC-BY sen versión e 2.174 rexistros cun patrón de correo que
require revisión de privacidade. Son sinais, non decisións legais nin unha listaxe
completa de datos persoais. A preparación de **novos snapshots** agora manda URLs
inválidas ou con eses identificadores a revisión; o snapshot contado non se reescribe.

Os hashes, os totais por fonte/categoría e os pendentes quedan nos JSON de
`evidence/`. O rexistro de dereitos enlaza as fichas capturadas, pero todas as
decisións continúan pendentes: ter unha ficha con licenza non aproba cada obra.
O resultado de readiness non permite construír o dataset como listo nin autoriza
adestramento. A corrección do desbalance require selección por contido, revisión
de fontes e novos datos con procedencia pechada; non duplicar filas nin inventar
preguntas, permisos ou etiquetas para cubrir obxectivos.
