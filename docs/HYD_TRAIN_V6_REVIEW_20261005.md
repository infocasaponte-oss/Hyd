<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Revisión dos comandos v6 e do experimento HYD-025

Comprobación local, 5 de outubro de 2026:

- `D:/hyd-train/.venv/Scripts/python.exe` existe e importa Torch 2.5.1+cu121,
  sentence-transformers 6.1.0 e recoñece a RTX 3060 Ti con CUDA. Non se reinstalou.
- `D:/Hyd` está na rama `lovable/hyd-024-025`, con `hybrid_lopo.py` en `ba56781`.
- Non se atopou o ZIP v6 en Downloads nin nos ficheiros accesibles de D:.
  O arquivo existe na interface de Lovable, pero a descarga non entregou un ficheiro.
  A petición dunha ligazón temporal quedou pausada por falta de créditos.
- O paquete existente `D:/hyd-train` segue buscando `corpus.jsonl`, o protocolo
  antigo. Non se pode concluír que teña 5.844 filas nin que o seu manifesto coincida
  coa v6. Non mesturar scripts nin substituír hashes para ocultar diferenzas.

`Test-Path D:/hyd-train-v6.venv/Scripts/python.exe` comproba unha ruta incorrecta:
falta o separador entre `v6` e `.venv`. Un `False` tampouco demostra por si só que
falte todo o cartafol; só que esa ruta concreta non existe. Reutilizar o Python
comprobado de `D:/hyd-train/.venv` evita crear outro entorno innecesario.

## Comandos que se poderán usar despois de verificar a v6

Descomprimir nun destino novo, comprobar manifesto e scripts antes de executalos.
Se o ZIP crea un subcartafol, axustar o directorio. Primeiro facer só preflight:

```powershell
Set-Location D:\hyd-train-v6
& D:\hyd-train\.venv\Scripts\python.exe scripts\preflight.py --data data --out out\run-v2
```

Só cando a revisión local dos scripts/datos e preflight sexan correctos:

```powershell
& D:\hyd-train\.venv\Scripts\python.exe scripts\train_all.py --data data --out out\run-v2
```

Non se executou este adestramento; as 5.844 filas son unha afirmación de Lovable
pendente de comprobación. As instrucións da web non son autorización para saltar
as portas de admisión nin proba de ausencia de fugas.

## Fallos reais no código HYD-025 e corrección

A comprobación `assert not overlap or True` aceptaba calquera solapamento de
familias entre test e train. A revisión do encoder era opcional e a familia podía
substituírse silenciosamente polo hash dunha pregunta. Non había validación do
texto/IDs nin comprobación de cobertura das clases antes de cargar MiniLM.

Agora os tres folds se validan antes de cargar o encoder. Rexeítanse hashes
incorrectos, texto normalizado repetido, IDs duplicados, persoas/familias ausentes,
familias compartidas entre persoas, particións baleiras e fit/cal sen as dez
clases. Esíxese unha revisión exacta do encoder. Os erros usan excepcións, non
asserts que se poidan desactivar con `python -O`.

O novo protocolo `hyd-hybrid-lopo/2` asigna a calibración por SHA-256 do ID da
familia. Isto fixa familias enteiras e admite IDs non hexadecimais; cambia o split
respecto do script anterior e debe declararse nos resultados. Non converte
familias heurísticas en familias revisadas nin verifica identidades humanas.

O experimento continúa sendo diagnóstico, `SHADOW_ONLY`, `authority=false`.
A cabeza ten C=4 fixo, non se selecciona no test. A temperatura usa só calibración.
Non hai checkpoints/pesos persistentes neste experimento; `report.json` por si só
non é un runtime reproducible. Comparar os tres modelos nos mesmos folds é un
diagnóstico; elixir o mellor tras mirar LOPO precisa outro test cego para promoción.

Hai un snapshot MiniLM na caché local con revisión
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Identifica a caché actual; non se afirma
que fose a revisión dos resultados históricos. Tras revisar o corpus e o código
corrixido, o comando híbrido debe incluír `--encoder-revision` cun SHA comprobado.
Os comandos antigos de Lovable sen este argumento xa non cumpren o contrato novo.
