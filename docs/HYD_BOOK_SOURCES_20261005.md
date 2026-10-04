<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Fontes de libros e carga múltiple — 5 de outubro de 2026

As catro fontes propostas están no catálogo exportable
`config/corpus_book_sources.json` e na pestana Corpus do calibrador local.
Non se aproba un catálogo completo como dominio público. Hai que revisar obra,
autor, tradución, edición, territorio, condicións de acceso e reservas TDM.

| Fonte | Resultado da revisión | Incorporación |
| --- | --- | --- |
| [Elejandría](https://www.elejandria.com/aviso-legal) | Declara dominio público en España, pero o apartado 13 limita reutilizar recursos propios e contempla solicitar autorización para usos non comerciais/educativos. | Catálogo e ficha por obra; descarga masiva desactivada. Resolver condicións de edición e permiso da fonte antes de adquirir para o corpus. |
| [Textos.info](https://www.textos.info/preguntas-frecuentes) | Mestura dominio público, licenzas Creative Commons/copyleft e autorizacións específicas para publicar. O permiso concedido ao portal non se presume transferido a HYDRA. | Descubrimento limitado OPDS de metadatos; revisión individual de cada edición e licenza. |
| [Open Library](https://openlibrary.org/developers/licensing) | A declaración sobre a base de datos non resolve dereitos dos libros nin de todos os territorios. As súas [normas API](https://openlibrary.org/developers/api) reservan os dumps para acceso masivo. | Só metadatos; préstamos, acceso restrinxido e contorno de bloqueos excluídos. O robots capturado bloqueou a consulta automatizada proposta; non se fixo a consulta. |
| [Cervantes](https://www.cervantesvirtual.com/marco-legal/) | Inclúe obras protexidas accesibles por autorización e reclama dereitos nas edicións dixitais e na base de datos. O uso persoal non é unha autorización xeral de explotación. | Catálogo, ficha e revisión por obra/edición; non hai crawling masivo habilitado. |

En España non se debe programar «80 anos» como regra universal. O [artigo 26 da
LPI](https://www.boe.es/buscar/act.php?id=BOE-A-1996-8930#a26) establece a regra
xeral de vida máis 70 anos e a [disposición transitoria cuarta](https://www.boe.es/buscar/act.php?id=BOE-A-1996-8930#dtcuarta)
remite ao réxime anterior para autores falecidos antes do 7 de decembro de 1987.
Tamén hai que revisar traducións, material engadido e os dereitos de determinadas
edicións dos [artigos 129–130](https://www.boe.es/buscar/act.php?id=BOE-A-1996-8930#a129).
Non se afirma que todos eses dereitos correspondan automaticamente a calquera escaneo.

## Comprobación real de descubrimento

Textos.info devolveu 20 fichas no feed de novidades. As 20 carecen dunha
declaración de dereitos no feed; quedan pendentes, sen adquirir o contido dos libros.
Unha data de actualización do feed tampouco proba que a obra sexa recente.
Open Library devolveu unha política robots que bloquea a ruta consultada: o
descubrimento gardou o bloqueo e non buscou un mecanismo para contornalo.
Os manifests agregados están en `evidence/book-discovery-*-20261005.json`;
os feeds e as fichas con autoría permanecen no directorio local de artefactos.

```powershell
python -m hyd_calibrator discover-books --catalog config/corpus_book_sources.json --source textos-info --out <directorio-novo>
```

As páxinas legais captúranse separadamente con URL, data e hash. As declaracións
dos portais son evidencia de condicións, non unha certificación de cada obra.
Gardáronse tres páxinas legais; a copia local de Cervantes devolveu HTTP 522.
O seu marco legal puido revisarse pola ferramenta web, pero non se inventa un
hash dunha copia que non se conseguiu gardar.
Non se publicou contido de libros ou datos persoais desas páxinas no repositorio.

## Descarga revisada por obra

O descargador nativo acepta `hyd-corpus-download-plan/2` para libros das fontes
habilitadas, cun `work_review` de formato `hyd-book-work-review/1`. Require unha
revisión humana identificada, obra e edición concretas, URL exacta, licenza,
territorio ES e revisión de dereitos da obra/tradución/edición, acceso á fonte,
reservas TDM e atribución. Os ficheiros de evidencia deben acompañar o plan con
rutas relativas seguras e SHA-256 comprobados **antes de acceder á rede**.
Un plan /1 e unha caixa «dereitos revisados» non habilitan libros. Open Library
non está habilitada como fonte de descarga de contido.

O resultado conserva a revisión por obra. A descarga segue sen autorización de
adestramento: privacidade, extracción, balance, descontaminación e reconto de
tokens teñen que facerse sobre o dataset preparado, non só sobre metadatos.

## Adxuntar varios ficheiros descargados

Na pestana **Corpus → Adxuntar obras descargadas**, seleccionar varios PDF,
EPUB, TXT, HTML, HTM, MD ou MOBI. Admiten ata 20 MiB por ficheiro, 100 ficheiros
e 500 MiB por lote. Cárganse un por un; se falla unha carga, as anteriores quedan
gardadas e a selección conserva os ficheiros restantes. Non se sobrescriben.

O servidor local garda `asset.raw` e `manifest.json` por ficheiro, cun identificador,
nome orixinal, SHA-256, bytes e procedencia declarada. As contas quedan separadas.
O botón de exportación entrega o inventario; os binarios permanecen no disco local
e nos orixinais do usuario. Non se executan, extraen ou admiten para adestramento.

Configurar `HYD_CORPUS_IMPORT_DIR` como ruta absoluta. Se non existe, úsase
`HYD_CORPUS_QUEUE_DIR/_imports`. Sen directorio configurado, a UI indica que a carga
non está habilitada. A aplicación segue requirindo o seu acceso autenticado.
Esta entrega modifica a copia local exportable; non desprega cambios en Lovable.

Tamén hai importación nativa, útil sen sesión web e para ficheiros de ata 200 MiB:

```powershell
python -m hyd_calibrator import-book-assets --input <carpeta-so-con-obras-seleccionadas> --source textos-info --out <directorio-novo>
```

Copia ata 100 ficheiros regulares dun só nivel; rexeita enlaces, subcarpetas,
executables, formatos descoñecidos e saída dentro da entrada. Comproba o hash do
orixinal despois da copia e non move nin borra os ficheiros do usuario.

## Diversidade e pasos que seguen pendentes

A literatura pode ampliar xéneros, pero engadir clásicos non resolve por si só a
escaseza de castelán conversacional e ciencia contemporánea. As fichas recentes
non se contan como texto moderno sen revisar o contido e a edición.
Non aumentamos tokens do corpus nin declaramos ningunha destas obras admitida.
Queda seleccionar edicións concretas con dereitos claros, extraer e revisar
calidade/privacidade, contrastar contra as preguntas humanas e benchmarks,
illalas por obra/edición e recontar co tokenizador propio antes de adestrar.
