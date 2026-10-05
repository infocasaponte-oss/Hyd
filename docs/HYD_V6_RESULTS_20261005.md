<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# V6: preguntas admitidas para desenvolvemento e experimentos reais

5 de outubro de 2026. O usuario pediu conservar as súas preguntas e as achegadas
por outras persoas, incluíndo numeración e cambios de datos. Unha marca automática
de posible molde non é unha prohibición nin unha decisión sobre a autoría humana.
Serve para analizar diversidade e organizar a avaliación; non exclúe por defecto.

## Paquete comprobado

ZIP orixinal: SHA-256 `203bdd3530e4a141005cd5623eff9b281f5d7c9d62841b796b9c14010ff10e02`.
Os 19 ficheiros enumerados no manifesto coinciden cos seus hashes. README e
manifesto non están cubertos pola lista de hashes; non se executaron instrucións
de instalación nin cambios de hooks. Descomprimiuse sen sobrescribir o paquete
anterior, en `D:/hyd-train-v6`, eliminando só o nivel externo de directorio do ZIP.
O preflight orixinal rematou con **0 erros e 0 avisos** no Python existente.

`corpus_v2.jsonl` contén **5.844 preguntas** co texto e hash correctos:

| Persoa declarada | Preguntas |
|---|---:|
| Propietario, dúas contas xuntas | 2.598 |
| Juan | 1.000 |
| Conta nova | 2.246 |

Usáronse tamén as **1.501 preguntas coa marca previa de posible molde**. Non se
quitaron números, non se reescribiron preguntas e non se cambiaron etiquetas.
As 392 copias exactas apartadas polo construtor da v6 seguen identificadas no ZIP;
non se borraron os datos orixinais. Non hai conflitos apartados nesta v6.

Hai 5.568 familias heurísticas, 192 con variantes e 468 filas nesas familias.
O construtor xera a familia sobre unha copia normalizada; conserva intacta a
pregunta. Comprobouse que as familias non cruzan persoas nin fit/cal/test nos
folds utilizados. A regra automática non detecta todas as paráfrases semánticas:
isto non certifica unha separación perfecta de escenarios.

## Implementación

- O importador do calibrador admite `suspect_template=true` e conserva o flag.
  Non decide se unha persoa é lexítima por escribir un número ou variar un dato.
- `hyd_calibrator.contributed_lopo` admite para desenvolvemento preguntas con
  declaración de titular/contribuínte e consentimento explícito. Non inventa
  verificación por terceiros nin cambia a orixe para facer pasar unha porta.
- A persoa deixada fóra non participa no fit nin na calibración. A familia enteira
  vai ao mesmo lado. C=4 está fixado; a temperatura usa só calibración.
- Esíxese a revisión real de MiniLM; gardanse cabezas, temperaturas, probabilidades
  por pregunta e hashes dos datos/código/artefactos. Os checkpoints rexeitan outra
  combinación de datos, código, semente ou encoder e comproban os ficheiros ao
  retomar. Un cambio posterior do código pode obrigar a un run novo.
- Non se instalaron paquetes nin se modificou a configuración da GPU. Ambos
  experimentos executáronse na RTX 3060 Ti, con MiniLM conxelado; isto adestra as
  cabezas de clasificación, non preadestra un modelo de linguaxe.

Revisión: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Corpus SHA-256:
`c52e4a5f3fdbef5ea1be74acc6a4087f468dc6fa298ef4c9fc4d9afdfd96908a`.
Non se afirma que esta revisión fose a dos resultados históricos.

## Resultados do experimento híbrido

Mesmos folds e preguntas para as tres representacións, semente 42:

| Persoa deixada fóra | Hash de Hyd + cabeza loxística | MiniLM | Hash + MiniLM |
|---|---:|---:|---:|
| Propietario | 27,75 % | 52,89 % | 52,93 % |
| Juan | 53,20 % | 73,30 % | 78,80 % |
| Conta nova | 37,62 % | 55,43 % | 56,37 % |
| Conxunto dos folds | 35,90 % | 57,36 % | **58,68 %** |

O híbrido acerta 3.429/5.844; o hash, 2.098/5.844. A media dando o mesmo peso a
cada familia é 58,56 % para o híbrido. A cabeza hash deste experimento é loxística:
non confundir esta comparación cunha nova medida do ranker activo de Hyd.

O run separado E2/E3 deu E2 55,03/73,40/52,93 % (conta nova/Juan/propietario) e
E3 74,35/82,90/71,98 %. E3 ten cinco rutas agregadas de risco, fronte ás dez de E2:
a súa accuracy non é directamente comparable. Os dous runs semánticos usaron
lotes distintos de inferencia fp16; non se presentan como predicións idénticas.

Os resultados son diagnósticos de desenvolvemento. A selección posterior entre
modelos mirando estes folds require outro test reservado para promoción. A clase
chat non ten soporte no fold da conta nova; o macro-F1 informa clases con soporte.
Non se alcanzou o obxectivo do 90 % e non se activou ningún modelo no motor.

## Anotacións e recarga

A v6 declara 750 marcas: 664 orixinais e 86 reconfirmadas. O ficheiro non inclúe
o actor/data/evento completo de cada revisión; consérvase esa limitación, sen
desautorizar as persoas nin inventar historial. Hai **696 marcas** vinculadas ao
corpus deduplicado (614 orixinais e 82 reconfirmadas); as outras 54 seguen no
export, pero non pesan nesta avaliación sobre os rexistros únicos.

E3 informa recall de abstención e de calquera risco por tipo/orixe declarada.
Non inventa precisión ou falsas alarmas por tipo: estas marcas só achegan
positivos e non anotacións negativas explícitas para eses conceptos.

Recargouse MiniLM e as seis cabezas E2/E3 e repetíronse as predicións das 5.844
preguntas. Diferenza máxima de embeddings e probabilidades: **0,0**. A comprobación
é de recarga/reproducibilidade, non unha nova medición de accuracy nin unha
acreditación de produción. As nove cabezas híbridas tamén pasan a paridade ao
gardar/recargar usando os embeddings do experimento.

Pesos/datos/predicións privados quedan en `D:/hyd-train-v6/out/`. Só se publica
o resumo `evidence/hyd-v6-development-20261005.json`; non preguntas nin correos.

## Repetir ou continuar

Desde o repo actualizado de Hyd, escoller unha saída nova:

```powershell
& D:\hyd-train\.venv\Scripts\python.exe -m hyd_calibrator.contributed_lopo --corpus D:\hyd-train-v6\data\corpus_v2.jsonl --marks D:\hyd-train-v6\data\abstain_marks_750.jsonl --out D:\hyd-train-v6\out\NEW_RUN --encoder-revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42
```

`--resume` só retoma un checkpoint compatible. Conservanse os scripts orixinais
da v6 sen alterar o seu manifesto. O seguinte paso é analizar erros por escenario
e mellorar representación/selección en desenvolvemento, mantendo todas as variantes
útiles e reservando novas preguntas para unha comprobación independente.
