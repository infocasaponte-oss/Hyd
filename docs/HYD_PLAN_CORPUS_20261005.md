<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Hyd: plan de preparación, resultado piloto e capacidade do corpus

Data: 5 de outubro de 2026, Europe/Madrid. Evidencia agregada e hashes: `evidence/hyd-corpus-plan-20261005.json`.

## Decisión

Preparar primeiro un Hyd reproducible e medible, conservando a súa separación do motor e unha interface exportable para a fábrica de HYDRA. Non aumentar o tamaño do modelo para compensar etiquetas, procedencia ou particións incompletas. A prioridade é mellorar abstain, tool_use e high_risk_review e probar a recarga real de E2.

O corpus actual permite reproducir o clasificador e estudar a base propia de 125M xa adestrada. As novas adquisicións aínda non están admitidas para outro preadestramento. A recomendación para a seguinte execución é un piloto da base propia de 125M con datos novos equilibrados e revisados. Un modelo de 350M será unha etapa posterior condicionada aos tokens útiles, resultados e cómputo; os datos medidos non xustifican un 4B/7B xeral desde cero.

Hyd clasifica preguntas con etiquetas humanas. HYDRA Base aprende a predicir texto sen esas etiquetas. Unha boa nota de Hyd non acredita por si soa a calidade, os dereitos nin a diversidade do corpus para un modelo de linguaxe.

## 1. Proba executada nesta entrega

Adestramento supervisado real do clasificador hash, 512 dimensións de estado e 128 de opción, 80 épocas, semente 42. Empregáronse os ficheiros xa preparados: 1.449 train, 315 calibración e 313 test. Todas as filas teñen consentimento e declaración de dereitos verificada no export; isto rexistra a declaración, non unha nova auditoría legal independente.

| Medida | Resultado |
|---|---:|
| Acertos no test histórico | 223 / 313 |
| Accuracy global | 71,25 % |
| Macro-F1 | 69,23 % |
| ECE | 5,96 % |
| Recall abstain | 48,39 % |
| Recall tool_use | 52,17 % |
| Recall high_risk_review | 61,90 % |
| Cobertura coa calibración esixida | 0 % |

A calibración buscou límite inferior Wilson do 95 % de confianza ≥95 % e cobertura ≥10 %. Ningún limiar probado cumpriu ambos requisitos. Mesmo 62/62 acertos na calibración teñen límite inferior 94,17 %. O resultado foi `target_met=false`, `abstain_all=true`, `SHADOW_ONLY`: non se promove nin se habilita autoridade. A accuracy entre respostas aceptadas é indefinida cando non se acepta ningunha, non cero nin 100 %.

Os pesos e os resultados completos permanecen en `D:/HYDRA/.codex-artifacts/hyd-pilot-20261005/`. Esta é unha reprodución diagnóstica co test histórico, xa consultado. Non é un novo test cego. Estes exports tampouco inclúen `person_id`/`family_id`; non se certifica separación por persoas e familias.

Resultados anteriores, con protocolos distintos: E2 gardado informa 85,3 % en 313 preguntas pero precisa verificar inferencia/recarga co contrato actual. O informe da base propia de 125M informa 50,2 % no test humano e v8 71,8 %, pero falta ligar esa comparación ao dataset exacto. Non se comparan esas cifras como se compartisen un mesmo test.

## 2. Corpus de preguntas de Hyd

O export preparado ten **2.077 preguntas**, con distribución bastante equilibrada por clase; equilibrio numérico non demostra variedade de autores, escenarios ou familias.

| Clase | Preguntas | % das preguntas |
|---|---:|---:|
| chat | 208 | 10,01 |
| coding | 213 | 10,26 |
| reasoning | 208 | 10,01 |
| research | 200 | 9,63 |
| vision | 229 | 11,03 |
| tool_use | 218 | 10,50 |
| abstain | 200 | 9,63 |
| security | 201 | 9,68 |
| privacy | 200 | 9,63 |
| high_risk_review | 200 | 9,63 |

Partición actual: train 69,76 %, calibración 15,17 %, test histórico 15,07 %. Non inventar autores novos a partir de contas distintas dunha mesma persoa. As 521 preguntas apartadas por indicios de molde non se reincorporan automaticamente nin se presentan como xeradas por IA sen evidencia.

## 3. Novas adquisicións: snapshot auditado

Snapshot selado do 4 de outubro, tokenizado co SentencePiece propio de 32.000 pezas. Ten 171.200 rexistros e **857.674.669 tokens de contido medidos** entre as tres particións. Un rexistro candidato non se puido medir: os porcentaxes de tokens usan só o total medido. Ningún reconto é unha autorización de adestramento.

| Estado | Rexistros | % rexistros | Tokens medidos | % tokens medidos |
|---|---:|---:|---:|---:|
| Candidatos pendentes | 115.971 | 67,74 | 721.385.900 | 84,11 |
| Duplicados | 4.073 | 2,38 | 25.711.818 | 3,00 |
| En revisión | 51.156 | 29,88 | 110.576.951 | 12,89 |

Os candidatos son **100 % EUR-Lex**. O 51,64 % dos seus tokens está etiquetado como lexislación e o 48,36 % como lingua moderna, pero ambos grupos son desta fonte legal. A etiqueta non os converte en conversa moderna.

| Fonte, incluíndo revisión e duplicados | % dos tokens medidos |
|---|---:|
| EUR-Lex | 87,12 |
| Common Corpus, varias coleccións | 7,04 |
| YouTube Commons | 4,95 |
| DGT | 0,74 |
| BSC corpus legal paralelo | 0,15 |

O **0 % dos novos candidatos está confirmado como listo** polo rexistro de readiness. Iso non significa que todo sexa ilegal ou inutilizable: significa que a revisión necesaria non rematou. Pendentes: alcance dos dereitos e atribución, acceso/TDM, privacidade, diversidade, idioma e descontaminación. Resolver tamén o candidato sen medir e os identificadores de orixe inválidos. Non substituír unha revisión humana por unha etiqueta de licenza do downloader.

## 4. Descargas máis recentes e corpus histórico

Os manifestos actuais do downloader, lidos nesta entrega sen deter os procesos, declaran **189.365 rexistros e 3.943.666.496 caracteres**. A lectura é por manifesto, non un snapshot transaccional de todo o corpus. Non se contou aquí o tokenizador sobre todo este inventario novo, nin se comprobou cada ficheiro contra o manifesto.

| Categoría declarada | % caracteres, inventario actual |
|---|---:|
| Lingua moderna | 51,73 |
| Lexislación | 45,41 |
| Ciencia | 2,86 |

EUR-Lex representa preto do 87 % dos caracteres declarados. A presenza de lingua moderna segue sen demostrar equilibrio conversacional. As categorías sen achega nestes manifestos non teñen progreso acreditado nesta lectura. Non actualizar `current_tokens` do plan usando caracteres/3,9 como se fosen tokens válidos.

O corpus histórico empregado pola base 125M é outro dataset: 252.833 documentos, 854.577.886 tokens train e 9.430.961 de validación. A distribución por fonte que se pode calcular exactamente do manifesto é **por caracteres**, non por tokens:

| Fonte histórica | % caracteres |
|---|---:|
| Libros PleIAs | 57,86 |
| BOE | 18,21 |
| Prensa PleIAs | 17,00 |
| Markdown | 4,91 |
| Python | 1,87 |
| Lotes técnicos | 0,15 |

Libros/prensa suman 74,86 % dos caracteres. O log final da base 125M confirma perplexidade 30,09 e perda de validación 3,404. Non se afirma que a nova adquisición xa se usase neste modelo. Tampouco se suman corpus histórico e novo para obter tokens únicos: primeiro hai que deduplicar entre ambos e reservar as avaliacións.

## 5. Que modelo podemos preparar

Empregamos **20 tokens por parámetro como referencia de planificación**, aproximada a partir da investigación de escalado compute-optimal, non como requisito universal nin garantía de capacidade. O tipo, calidade, repetición e dominio dos datos cambian a decisión. Repetir épocas non crea novos tokens únicos.

| Modelo textual desde cero | Referencia de tokens de adestramento | Decisión |
|---|---:|---|
| 30–50M | 0,6–1B | Escala razoable para un piloto especializado, logo de admitir datos; non un asistente xeral certificado |
| 125M | 2,5B | Continuar a base xa existente en lotes equilibrados e revisados, con control de retención; non volver empezar por defecto |
| 350M | 7B | Preparar cando haxa volume útil e diverso suficiente e un benchmark de cómputo |
| 1B | 20B | Non sustentado polo reconto admitido actual |
| 4B | 80B | Non sustentado para preadestramento xeral desde cero |
| 7B | 140B | Non sustentado para preadestramento xeral desde cero |

A suma exacta dos obxectivos de config/base_categories.json é 7.000.000.000 tokens útiles (7B); o texto de propósito aínda fala de ~6B e debe actualizarse. É un obxectivo, non un reconto conseguido. Coa mestura actual non recomendo lanzar un 350M–1B. Unha boa nota de Hyd permite decidir sobre ese clasificador; escalar HYDRA require tamén perplexidade por dominio, probas de coñecemento/retención, contaminación e custo.

Un 7B cuantificado pode ser outra vía de **axuste dun modelo xa preadestrado**, suxeita á súa licenza e recursos; cuantificar para inferencia non equivale a poder preadestralo. Un 4B VL necesita imaxes e datos multimodais revisados que non están acreditados neste corpus de texto. Non se compromete gasto en GPU remota.

Hardware observado: RTX 3060 Ti, 8 GB. A base 125M rexistrou arredor de 8.600 tokens/s coa receita antiga; non extrapolar ese rendemento a outra arquitectura. Cada nova receita require un benchmark de 200–500 pasos e unha estimación medida de memoria, tokens/s, tempo e custo.

Fonte primaria: [Training Compute-Optimal Large Language Models](https://arxiv.org/abs/2203.15556).

## 6. Plan de implementación e probas, por orde

| Fase | Traballo concreto | Proba / condición de saída |
|---|---|---|
| 0. Conxelar referencias | Gardar código, pesos, tokenizador, criterios, filas e hashes dos resultados actuais | Recarga e inferencia reproducibles; ningunha cifra sen dataset identificado |
| 1. Exportar Lovable | Recuperar preguntas completas, consentimentos, histórico de correccións, anotacións perigosa/falta de contexto, seleccións humanas, predicións e versións E1/E2/E3 | Recontar export contra BD; conservar orixinais e campos; non converter opinión IA en etiqueta correcta |
| 2. Resolver datos | Adxudicar desacordos e documentar persoas/familias reais; distinguir risco de falta de contexto | 100 % das filas admitidas con referencia/procedencia explícita; rexistro de exclusións e versións |
| 3. Particións | Crear train/dev/cal/test por compoñentes persoa/familia/texto; reservar test cego novo | Cero solapamento por grupos; usar o test histórico só como regresión; non inventar metadatos |
| 4. Clasificadores | Baseline TF-IDF word/char; E2 real coa revisión do encoder fixada; cabeza da base propia 125M e v8 como referencia | Selección só en dev, sementes 17/42/73, parada temperá e comparación pareada sobre a mesma mostra; non elixir parámetros en calibración/test |
| 5. Calibración e E3 | Calibrar o gañador; aprender limiares de confianza/marxe; avaliar perigosa e falta de contexto con anotacións confirmadas | Accuracy, macro-F1, ECE/NLL, cobertura e Wilson; precision/recall e falsas alarmas de E3 só coa poboación/negativos realmente anotados |
| 6. Integración | Hyd en sombra no motor; calibrador/corpus como ferramentas da fábrica; adaptador e ficheiros propios exportables | Paridade lote/unitario e gardar/recargar; erros/timeout; autoridade false; reversión sen perder datos |
| 7. Corpus LM | Resolver revisións, limpar/deduplicar entre datasets, descontaminar e recontar tokens propios; seleccionar mestura por rexistro/idioma/fonte | Manifesto selado e revisión rexistrada; readiness true só cando corresponda; non adestrar cos candidatos pendentes |
| 8. Piloto da base | Primeiro 10–20M tokens revisados para validar a receita e retención, logo ampliar a execución de 125M | Curvas train/val por dominio; benchmark de hardware; comparar perplexidade co mesmo tokenizador/documentos e Hyd no mesmo protocolo |
| 9. Promoción e escala | Avaliar o artefacto selado nun test cego e decidir seguinte tamaño | Se falla un criterio, conservar resultado e recoller datos; non retocar o test nin afirmar un 90 % inexistente |

Proposta de criterio Hyd a fixar **antes** da nova selección: accuracy global ≥90 %, macro-F1 ≥0,90; por separado, precisión selectiva con límite inferior Wilson ≥95 % e cobertura obxectivo ≥50 %. Reclamar tamén recall ≥95 % nas clases de risco previamente definidas, rexistrando soporte e intervalo. Son obxectivos propostos, non resultados conseguidos; se a mostra non ten tamaño suficiente, a conclusión será inconclusa. Nunha regresión de 313 casos, 282 acertos superan o 90 % puntual; iso non certifica o límite inferior do intervalo nin un test independente.

Balance piloto LM proposto, pendente de revisión da fábrica: polo menos 30 % dos tokens de lingua moderna non legal/conversacional; legal/administrativo como máximo 20 %; literatura/prensa histórica como máximo 20 %. O resto distribúese en ciencia/educación, documentación, matemáticas e código segundo dispoñibilidade admitida. Son restricións do próximo piloto, non unha medición do corpus nin unha proporción óptima demostrada. Se non hai fontes suficientes, reducir o lote; non cubrir ocos duplicando texto legal.

## 7. Traballo con Lovable ás 02:00

Ás 02:00 do 5 de outubro, hora de Madrid, empregar a sesión dispoñible para exportar primeiro os datos/código/SQL e comprobar as anotacións. Cos cinco créditos, priorizar a corrección ou integración concreta pendente, con export antes/despois e proba gardar–recargar–exportar. Non consumir créditos pedindo que a IA xere preguntas supostamente reais. Non se programou unha conexión automática nin unha tarefa recorrente.

Datos que precisamos do export: IDs estables, pregunta orixinal, clase humana e historial, consentimento/dereitos, persoa e familia **declaradas**, procedencia, tipo de abstain e estado/autor da revisión, predicións con modelo/versión/hash e data. Manter identificación persoal na exportación privada; o informe/GitHub inclúe agregados e códigos, non correos.

Antes dun novo preadestramento LM quedan por pechar as admisións do corpus. Antes de promover Hyd quedan a reprodución de E2, o test novo por grupos e as anotacións reais de E3. O piloto desta entrega é diagnóstico e non cambia o modelo activo.
