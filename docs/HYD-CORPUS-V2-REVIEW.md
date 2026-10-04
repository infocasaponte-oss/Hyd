<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Revisión e continuación de v2 — 2026-10-03

PR revisado: https://github.com/infocasaponte-oss/HYDRA-SO/pull/109 .
Correccións publicadas na revisión `8e214bb0cc27c8dc419bb84506642af1158687a1`.
A CI anterior fallaba polo aviso de copyright ausente; foi corrixido.

Revisión posterior `d339bb9c6c1dd82c8275150c7c99ab954a9f768c`: resoltos
os cinco fíos de revisión. MinHash calcula mínimos sobre todos os shingles
en lotes de memoria limitada; non cambia a mostra segundo a lonxitude.
A descontaminación recolle tamén `provenance.document_id` de Stack; admite
avaliacións con BOM mantendo o hash dos bytes. A etapa 0 non require léxico OCR.
As 22 probas específicas de corpus/calidade pasan. O constructor reiniciouse
con esa revisión; a saída parcial anterior consérvase.

O PR fusionouse como `e0548ab70f60212b84ff8b3709a25a85f0b9c54c`.
A opción de fusión automática executou a fusión antes de completar a última
CI; recoñeceuse o erro e verificouse de novo a revisión. Non se debe usar
esa opción como substituto dunha comprobación explícita de todos os checks.
Verificación final: todos os checks da revisión `d339bb9` aprobados, incluídos
os dous jobs de Windows e os dous de Linux. Suite local completa final:
1.018 aprobadas, 87 omitidas, ningún fallo (126 segundos).

## Cambios comprobados

- Python valídase con `compile` despois de AST, sen executalo; rexeita `return`
  fóra dunha función e argumentos duplicados. Textos baleiros teñen un motivo explícito.
- O índice LSH conserva todos os candidatos de cada banda, non só o primeiro.
  Usa valores simples para bandas cun único candidato para limitar a memoria.
  A similitude é estimada: non equivale a unha garantía de recall ou Jaccard exacto.
- O léxico conxélase só con obras de train e licenzas admitidas. Un léxico
  baleiro non pode desactivar silenciosamente o filtro OCR.
- Os aliases locais de PleIAs non poden saír do directorio da fonte.
- Os hashes das avaliacións corresponden aos bytes lidos. Un cambio das
  avaliacións, o léxico, as regras ou o xerador impide selar o corpus.
- O manifest final escríbese atomicamente.

Validación na rama do PR: 1.016 probas aprobadas, 87 omitidas, ningún fallo;
probas específicas de corpus/calidade/copyright: 21 aprobadas; Ruff e diff-check
aprobados. Estes resultados verifican o código, non certifican aínda o corpus.
As porcentaxes de conservación da receita anterior deben medirse de novo.

## Procesos e autorización vixente

Detivéronse os traballos v1-r1 e o preparador asociado; conserváronse as saídas
parciais. Tamén se detivo o primeiro constructor v2 antes de editar os módulos
que usaba. Reiniciouse desde a revisión comprobada co lanzador mellorado
`runtime/build-corpus-v2.ps1`: bloqueo exclusivo, comprobación das entradas de
avaliación, estado atómico e erros explícitos. Usa o novo léxico
`data/sources/lexicon/hydra-es-lexicon-v2.txt` e o destino
`data/hydra-base-corpus-v2`. Non sobrescribe unha saída existente.

O usuario autorizou expresamente continuar todos os procesos, incluído o
preadestramento 125M segundo criterio técnico, priorizando o motor HYDRA.
O preparador espera co plan `runtime/hyd-stage1/professional-plan.json`:
revisión → tokenizador v2 → tokenización → base 125M → candidato contextual Hyd.
Non crea GGUF nin habilita autoridade aprendida.

Os fallos de integridade sempre bloquean. Os avisos de calidade precisan unha
revisión documentada, con evidencia, vinculada ao hash exacto do informe, ao
manifest do corpus e aos contadores de avisos. Non se xerou ningunha aprobación
anticipada. Isto non é un verificador autónomo de comprensión: a calidade das
evidencias segue requirindo análise.

Hai seguimento cada 30 minutos na conversa, `continuar-corpus-v2-e-hyd`, que
revisará cambios accionables e resolverá fallos verificables. Permanecerá en
silencio mentres o estado non necesite intervención. MoE segue aprazado.
