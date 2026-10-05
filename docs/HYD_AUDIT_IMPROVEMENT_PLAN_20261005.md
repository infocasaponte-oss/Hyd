<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Hyd: auditoría medida e plan de afinamento e calibración

5 de outubro de 2026. Repo: `infocasaponte-oss/Hyd`. Código auditado:
`42cd62e7cb7d4d2764d1c2b5222c37f3f20435ec`. Non se activou ningún modelo,
non se modificaron preguntas/etiquetas e non se cambiou a visibilidade do repo.

## 1. Actions e publicación

O usuario comunicou que o repo xa está público. Na comprobación posterior con
`gh repo view`, a API seguía devolvendo `PRIVATE` tanto para Hyd como para
HYDRA-SO: queda por confirmar o cambio efectivo ou o repo exacto. Non se cambiou
a visibilidade desde esta tarefa. No run `37287884016`, os dous jobs remataron como failure
con **cero pasos executados**. A anotación do check `111691036721` di que o job
non empezou por pagamentos fallidos ou límite de gasto. É un bloqueo de
infraestrutura/facturación; non demostra un fallo das probas.

GitHub documenta que os runners estándar son gratuítos en repos públicos e que
os privados teñen unha cota. Isto non require converterse nunha empresa. Non
garante que todas as probas pasen ao cambiar a visibilidade, nin resolve por si
só calquera restrición da conta.

Fonte oficial: https://docs.github.com/en/billing/concepts/product-billing/github-actions

**Repo afectado: Hyd, non HYDRA-SO neste diagnóstico.** Antes de publicar o repo
enteiro hai que decidir que material se quere facer público. O checkout xa
contén `data/hyd-app-records/hyd-real-corpus-2026-10-04.jsonl` e
`hyd-sospeitosas-molde-2026-10-04.jsonl`; aparecen tamén no historial. Hai máis
corpora baixo `data/` e a licenza actual é propietaria. Pseudonimizar o correo
non elimina o contido persoal que poida aparecer nunha pregunta. Borrar estes
ficheiros nun commit novo non os retira dos commits anteriores.

Se Hyd xa se fixo público, a opción de traballo é usar ese repo e comprobar as
Actions nel; non fai falta crear outra copia para este cambio. Cómpre revisar
que material se publicou, incluído o historial. Un repo independente de código
e probas sen historial privado segue sendo unha alternativa se se decide separar
o corpus. Non se creou outro repo nin se retirou material nesta tarefa. Esta
auditoría identifica exposición de corpus: **non certifica ausencia de segredos
en todo o historial**.

Para esa copia pública:

1. Código, manifests, documentación agregada e fixtures artificiais identificadas.
2. Separar tests autocontidos dos que precisan corpus privado. Por exemplo,
   `tests/test_evaluate_decision_corpus.py` le directamente `data/decision-corpus-v3/`.
   Crear fixtures públicas suficientes e conservar a avaliación privada local.
3. CI en Ubuntu e Windows estándar, permisos mínimos de lectura, sen credenciais
   privadas nin subida de corpus/pesos como artefactos. Non usar un runner local
   con acceso a datos privados para executar PRs de terceiros.
4. Aplicado ao workflow de Hyd: limitar push a main, conservar pull_request,
   engadir workflow_dispatch para repetición manual, cancelar execucións
   obsoletas, permisos contents:read e timeout de 20 minutos por job. Mantéñense
   as probas Ubuntu/Windows e a comprobación da CLI. Non se quitaron probas.
5. Validar un checkout limpo nesa copia e comprobar a execución real das Actions.

Alternativa: revisar/sanear completamente o historial de Hyd antes de publicalo.
É máis custoso e require planificar a reescritura e os clones existentes. Non
se realizou esa operación nin se alterou a facturación.

## 2. Evidencia e alcance

Analizáronse as probabilidades gardadas do experimento híbrido LOPO/2. Cada unha
das 5.844 preguntas aparece exactamente unha vez como persoa deixada fóra.
Comprobáronse hashes dos ficheiros de predición, correspondencia ID/persoa/hash
do texto, cobertura completa e suma das probabilidades. O reconto reproduce
os 3.429 acertos publicados. A evidencia agregada, sen preguntas nin IDs, está
en `evidence/hyd-v6-error-audit-20261005.json`.

Corpus SHA-256:
`c52e4a5f3fdbef5ea1be74acc6a4087f468dc6fa298ef4c9fc4d9afdfd96908a`.
Encoder MiniLM conxelado, revisión:
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
Cabezas loxísticas C=4; temperatura axustada só na calibración. Non houbo
afinamento do encoder nin selección de hiperparámetros nun dev separado.

As tres persoas son declaradas; dúas contas do propietario contan como unha.
Mantéñense as 1.501 preguntas coa marca previa de posible molde: a marca non
invalida a pregunta nin acredita unha orixe artificial. As familias son
heurísticas, non unha certificación de independencia semántica.

| Representación | Acerto global |
|---|---:|
| Hash 512 + cabeza loxística | 35,90 % |
| MiniLM conxelado | 57,36 % |
| Hash + MiniLM | **58,68 %** |

O hash deste experimento non é unha nova avaliación do ranker activo de Hyd.
O híbrido dá macro-F1 agrupado de **60,11 %**, ECE de 10 bins **0,1884** e
NLL **1,5489**. O acerto entre persoas vai de 52,93 % a 78,80 %. Esa diferenza
xustifica comprobar xeneralización; non permite concluír quen escribe mellor
nin se unha pregunta é válida.

## 3. Erros que determinan a prioridade

| Clase esperada | Casos | Recall | F1 |
|---|---:|---:|---:|
| abstain | 934 | 58,57 % | 57,91 % |
| chat | 344 | 55,81 % | 56,64 % |
| coding | 363 | 81,54 % | 73,09 % |
| high_risk_review | 740 | 71,62 % | 62,95 % |
| privacy | 382 | 47,64 % | 49,66 % |
| reasoning | 438 | 84,93 % | 88,15 % |
| research | 438 | 54,79 % | 60,91 % |
| security | 385 | 50,65 % | 51,86 % |
| tool_use | 909 | 48,18 % | 47,92 % |
| vision | 911 | 47,97 % | 51,96 % |

Hai 2.415 erros. As confusións vision→tool_use (245) e tool_use→vision (146)
suman **391**; tool_use→coding engade 115. Hai 99 abstain→chat e 89 casos de
privacy→high_risk_review e outros 89 de security→high_risk_review. Cómpre revisar
o contrato das rutas e se o texto achega as capacidades/contexto necesarios.
Estas son hipóteses a comprobar con exemplos reais; non unha orde de cambiar
as etiquetas para que o modelo acerte.

## 4. Confianza e abstención

| Corte de confianza | Aceptadas | Cobertura | Acerto nas aceptadas | Erros |
|---|---:|---:|---:|---:|
| ≥ 0,80 | 3.128 | 53,52 % | 73,53 % | 828 |
| ≥ 0,90 | 2.287 | 39,13 % | 79,36 % | 472 |
| ≥ 0,95 | 1.675 | 28,66 % | **82,75 %** | **289** |
| ≥ 0,99 | 702 | 12,01 % | 88,18 % | 83 |

Esta táboa é diagnóstico de cortes fixos, non unha selección de limiar usando
o test. A confianza 0,95 non equivale a 95 % de acerto. Nin o corte 0,99 chega
ao 90 % neste conxunto. Reducir cobertura non resolve a representación.

A temperatura escalar positiva conserva o argmax: **non aumenta o acerto
global**. Pode mellorar probabilidades e selección de respostas; para mellorar
as rutas fan falta representación, adestramento e información adecuadas.

## 5. Plan executábel, por orde

### P0 — Fixar o contrato e o protocolo antes de experimentar

- Gardar esta baseline, hashes, revisións, predicións e métricas. Os folds xa
  consultados serán desenvolvemento; non presentalos despois como test cego.
- Especificar exemplos/contraexemplos humanos de vision/tool_use/coding e
  privacy/security/high_risk_review; decidir como tratar solicitudes que
  requiren varias rutas. Conservar texto e etiqueta orixinais; calquera revisión
  humana ten actor, data, motivo e versión da etiqueta, sen borrar o orixinal.
- Revisar erros nun ficheiro privado. Engadir só contexto real dispoñible na
  petición, como presenza de imaxe/ferramentas/contexto anterior. Non reconstruír
  retrospectivamente información inexistente para mellorar o resultado.
- Crear particións por familia dentro de cada fold: fit, dev de selección,
  calibración de probabilidades e calibración dos limiares. Nunca usar a persoa
  exterior para elixir parámetros. Comprobar soporte das clases en cada parte.
- Reservar novas preguntas e, se é posible, máis persoas para un test final
  independente. As preguntas propias seguen servindo para desenvolver/adestrar.
  As variantes quedan xuntas; non hai exclusión automática por números.

Entrega/proba: manifests e hashes por partición, cero cruzamentos de IDs,
textos exactos e familias coñecidas; informe de soporte por persoa/clase.

### P1 — Mellorar primeiro as cabezas e a representación barata

- Comparar TF-IDF disperso de palabras/caracteres coa representación hash 512,
  MiniLM e combinacións. Axustar vocabulario/IDF só con fit, evitando fuga.
- Seleccionar C, pesos de clases e peso de cada representación só no dev.
  Comezar cunha grella pequena C={0,1; 1; 4; 10}, sen/balanced e mestura
  hash/semántica={0; 0,25; 0,5; 1}; ampliar só cando a evidencia o xustifique.
- Comparar peso por rexistro con peso equilibrado por familia. Conserva todas
  as variantes útiles sen permitir que unha familia grande domine a perda.
- Repetir particións internas con sementes 17/42/73. Gardar tamén o peor fold,
  macro-F1 e recall de risco; non elixir só pola accuracy agrupada.

Entrega/proba: táboa emparellada sobre os mesmos casos, intervalos por bootstrap
de familias e custo/latencia. Só tres persoas non abondan para estimar con
precisión a xeneralización a toda a poboación.

### P2 — Afinar o encoder se P1 segue limitado

- Afinamento supervisado de MiniLM coa cabeza de dez rutas, mantendo a baseline
  conxelada como control. Usar só fit; early stopping e parámetros só no dev.
- Comezar con cabeza + últimas capas, poucas épocas, lotes pequenos/acumulación
  e precisión mixta. Medir primeiro memoria e tempo na RTX 3060 Ti de 8 GB;
  determinar o lote viable cunha proba curta, sen prometer capacidade ou horas.
- Comparar unha pequena grella de learning rates e graos de conxelación. Se
  se proba aprendizaxe contrastiva, usar pares confirmados e negativos revisados,
  sen asumir que unha familia heurística garante equivalencia de significado.
- Non introducir novos exemplos xerados como se fosen preguntas humanas. Se se
  usan datos sintéticos, identificar a orixe e facer unha ablación separada.

Entrega/proba: checkpoint/versiones/revisións, curva fit/dev, degradación por
clase/persoa e recarga completa co encoder afinado. Non activar automaticamente.

### P3 — Calibrar probabilidades e decisións por separado

- Conxelar o modelo seleccionado antes de calibralo. Comparar temperatura con
  outras calibracións só se hai soporte suficiente; informar NLL, Brier, ECE e
  fiabilidade por persoa/clase. Non sobreaxustar unha calibración por clase pequena.
- Axustar limiares de resposta/abstención nunha partición distinta da usada para
  temperatura. Avaliar cobertura, erro selectivo e derivación a revisión humana.
- Distinguir a clase humana abstain dunha abstención técnica por baixa confianza.
  Un modelo que se abstén de todo non supera o obxectivo de clasificación.
- Informar intervalos tendo en conta dependencia por familias e variación entre
  persoas. Unha garantía baixo unha distribución non proba seguridade fronte a
  outra; a diferenza entre persoas actual require especial atención.

Entrega/proba: política versionada de limiares, curvas risco/cobertura e
comprobación final nun test reservado que non decide ningún parámetro.

### P4 — E3 e integración no motor

- As 750 marcas declaran positivos; 696 enlazan co corpus único. Non abondan
  para medir falsas alarmas e precisión por tipo: recoller negativos explícitos
  e eventos de revisión, mantendo as marcas existentes e os textos orixinais.
- Avaliar separadamente perigo e falta de contexto; poden coexistir. E3 actual
  agrega cinco rutas e non acredita dous detectores independentes destes conceptos.
- Conectar contexto real, probabilidades e política calibrada mediante contrato
  exportable JSON/JSONL. Comparar coa decisión humana e co Hyd activo en shadow.
- Verificar recarga do encoder afinado/cabeza/política, paridade, compatibilidade,
  latencia e memoria; proba de rollback e ausencia de autoridade en shadow.

Entrega/proba: confusións por tipo, recall/precisión/FPR sobre positivos e negativos
humanos e rexistro de cada decisión, sen confundir a accuracy de cinco rutas coa
de dez.

## 6. Criterios de avance e obxectivo do 90 %

O 90 % é un obxectivo, non unha previsión. Non hai evidencia para prometer que un
modelo maior o conseguirá. Estes 5.844 casos son datos supervisados de rutas;
non son por si mesmos un corpus suficiente para preadestrar un LM de 4B/7B.

Antes de promoción, fixar por escrito: accuracy global e macro-F1 obxectivo,
recall mínimo de risco, erro selectivo admisible e cobertura mínima. Unha
proposta a validar é accuracy/macro-F1 ≥90 %, recall de risco ≥95 % e acerto
selectivo ≥95 % cunha cobertura útil acordada. Mostrar intervalos e resultados
por clase/persoa; non ocultar exclusións ou clases sen soporte. Hoxe non se
cumpren estes obxectivos.

Cada etapa continúa só se mellora a avaliación interna sen degradar rutas
críticas. Se non mellora, rexistrar o resultado e revisar contexto/contrato e
diversidade antes de aumentar tamaño. A calibración non substitúe ese traballo.

## 7. Comprobacións feitas e pendentes

Feito nesta auditoría: comprobación de repo privado, jobs sen pasos e mensaxe
de facturación; lectura do workflow e dependencias de corpus en tests; presenza
de corpus humano no checkout/historial; análise das 5.844 predicións verificadas
por hashes, métricas por clase e cortes fixos. Non houbo outro adestramento.

Validación anterior do código: 1.222 probas pasadas, 87 omitidas; recarga real de
MiniLM e seis cabezas E2/E3 con diferenza máxima 0,0. As novas métricas describen
os mesmos experimentos, non unha repetición independente.

Pendente: revisión exhaustiva de segredos e dereitos para publicación, copia
pública e CI real, protocolo interno dev/cal/limiares, comparacións P1, afinamento
P2, novas anotacións negativas E3 e test final novo. Non se presentan como feitos.
