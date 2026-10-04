<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Corpus local, papeleira e saída portable

O código do calibrador e os datos de adquisición poden funcionar fóra de Lovable.
A integración definitiva de Hyd no motor e da aplicación na fábrica segue sendo
un paso posterior: non se declara despregada nin se cambia o motor en produción.
Conservar JSONL, preguntas orixinais, correccións, anotacións humanas, consentimentos,
procedencia, manifests, pesos/tokenizador e resultados de avaliación por separado.
Os textos de preadestramento non substitúen as etiquetas humanas de Hyd.
As declaracións de licenza nos manifests non acreditan por si soas a admisión.

## Papeleira recuperable

`python -m hyd_calibrator plan-corpus-trash --root corpus/raw --out trash-plan.json`
busca só copias **idénticas byte a byte** de ficheiros finalizados `.jsonl.gz`.
Non move nada. Exclúe temporais, carpetas ocultas e manifests. Un duplicado textual
normalizado non é necesariamente unha copia idéntica: non se borra con este comando.

`python -m hyd_calibrator stage-corpus-trash --root corpus/raw --plan trash-plan.json`
comproba hashes e move esas copias a `corpus/raw/.trash/<batch>` cun manifest.
`restore-corpus-trash --root corpus/raw --batch <batch>` restaura sen sobrescribir.
`empty-corpus-trash --root corpus/raw --batch <batch>` elimina exclusivamente os
ficheiros dese lote; antes volve comprobar a copia conservada e o seu hash.
O manifest queda como evidencia. Un bloqueo exclusivo impide operacións simultáneas.
Tras unha caída revisar `operation.lock` antes de retiralo: non existe recuperación
automática dese bloqueo. Estes comandos non substitúen unha copia de seguridade.

Os rexistros en revisión por procedencia/licenza non van á papeleira automaticamente.
O descargador de categorías xa elimina os parquet de transferencia tras consumilos.
Non limpar `_tmp` mentres estea activo, nin eliminar manifests para recuperar espazo.

## Cola local

Configurar `HYD_CORPUS_QUEUE_DIR` no servidor Node da aplicación exportada cun directorio
persistente compartido co worker. Non almacenar isto nunha instancia serverless efémera.
Arrancar en PowerShell:

```powershell
./scripts/run_corpus_queue.ps1 -Root D:/HYDRA/runtime/corpus-download-queue -Python D:/HYDRA/.venv/Scripts/python.exe -CalibratorRoot <checkout-Hyd>
```

O worker mantén un bloqueo exclusivo, procesa ata dez tarefas por pasada e consulta
a cola cada dez segundos. Gardar `stop-worker` na raíz da cola pide deter o bucle
ao rematar a pasada; para cancelar unha transferencia usar a cancelación da tarefa.
`worker.pid` e `worker.log` permiten revisar a instancia. Se falla o CLI detense;
non repite automaticamente tarefas reclamadas tras unha caída. A aplicación require
a súa autenticación configurada; este worker non crea contas nin datos de proba.

Nesta máquina a cola está en `D:/HYDRA/runtime/corpus-download-queue` e o worker
local arrancou o 4 de outubro ás 23:16 (PID inicial 88936). A configuración local
da aplicación inclúe o directorio da cola, pero a aplicación non foi arrancada
nesta entrega e aínda necesita as variables de autenticación do destino.
O descargador de categorías xa activo é outro proceso: non comparte nin recibe
tarefas desta cola e non se arrancou unha segunda copia del.

## Paquete de código

`python scripts/export_hyd_factory.py --hyd <checkout-Hyd> --app <checkout-calibrador> --out <directorio-novo>`
crea dous ZIP dos commits e un manifest con SHA-256. Exclúe ficheiros locais non
rexistrados (incluído `.env`), rexeita cambios sen commit e `.env` rexistrados.
As credenciais do despregamento créanse no destino. Os ZIP son código, non unha copia
completa dos datos remotos: exportar ademais o arquivo completo e JSONL de Lovable
antes de desconectar a conta. Non se afirma que estes arquivos xa se descargasen.
Os pesos e corpus voluminosos requiren o seu propio inventario e transferencia.

## Comprobación nesta entrega

O descargador existente estaba activo e completou o lote YouTube `cctube_195.parquet`:
32.445 textos, 238.525.333 caracteres, segundo o seu manifest observado o 4 de outubro.
Son cifras de adquisición, non tokens nin datos admitidos para adestrar.
A exploración de 123 ficheiros finalizados non atopou copias binarias redundantes:
0 bytes recuperables por esta regra. Non se inventa unha limpeza nin se borran textos
para cumprir unha cifra. A exploración non é un snapshot transaccional da descarga activa.
Creouse e baleirouse un lote baleiro da papeleira: o seu manifest queda conservado;
non se eliminou ningún ficheiro de datos real. Pasaron 51 probas de adquisición,
cola, papeleira e E2/E3, ademais de Ruff dos ficheiros modificados.
O snapshot anterior conserva 115.971 candidatos, 4.073 duplicados e 51.156 rexistros
en revisión; candidatos tampouco significa aprobados para adestramento.
