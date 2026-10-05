<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Equilibrado e revisión asistida de Hyd

As preguntas do propietario e as variantes numéricas seguen sendo datos válidos de desenvolvemento. A revisión da IA produce propostas identificadas, non anulacións das preguntas nin confirmación humana. Non se cambian textos, autores nin as 629 etiquetas xa confirmadas na versión importada.

## Implementado

- Revisor local con identidade do modelo, hash de corpus e prompt, resposta orixinal gardada e recuperación verificable. O modo `--single` procesa unha pregunta por chamada e usa nomes de clase para evitar desaliñamentos de lotes.
- Pesos iguais entre as dez clases e entre familias durante o axuste. Unha variante non se elimina, pero tampouco multiplica artificialmente o peso da súa familia.
- 240 exemplos sintéticos, 24 por clase, en 60 familias. Son seis tarefas distintas por clase con catro formas de pedilas; non son 240 achegas humanas independentes.
- 12 contrastes para revisar: instrución citada fronte a execución, código fronte a acción irreversible, privacidade fronte a credenciais, tarefa visual fronte a contexto ausente. A etiqueta definitiva queda baleira; só existe unha suxestión da IA.
- Dúas receitas separadas: conservar etiquetas actuais e engadir sintéticos; ou probar propostas da IA só no axuste non confirmado e engadir sintéticos opcionalmente.
- Desenvolvemento, calibración de probabilidades, calibración de política e test mantéñense idénticos byte a byte. Ningún sintético entra na avaliación.
- Candidatos separados, recarga real do encoder e comparación cos resultados reais gardados de Kev, tras verificar os seus pesos e a calibración. Non hai promoción automática.

## Evidencia dispoñible

Referencia actual: 5.844 preguntas reais, tres autores e 629 etiquetas confirmadas pola revisión humana importada. É unha referencia xa inspeccionada e parcialmente revisada, non un novo test independente.

| Receita | Exactitude na referencia humana |
|---|---:|
| Hyd equilibrado, sen novos sintéticos | 56,38 % |
| Hyd equilibrado + 240 sintéticos, sen cambiar etiquetas reais | 56,91 % |
| Propostas individuais v8 + sintéticos (rexeitado) | 49,85 % |
| Kev, mesmos casos e pesos verificados | 48,37 % |

O incremento de 0,53 puntos non demostra que se alcance o 90 %. As tres recargas do ensaio con sintéticos pasan; ningún candidato pasa a política de fiabilidade. Mantéñense en observación.

A primeira pasada da IA con índices numéricos deu clasificacións claramente erradas e os candidatos empeoraron: 41,24 % sen sintéticos e 42,85 % con eles. A revisión individual con v8 completou as 5.844 preguntas, pero só deu 47,93 % sen sintéticos e 49,85 % con eles. Discrepou en 472 das 629 revisións humanas. Ambos ensaios quedan rexeitados; gardar unha proposta non a converte nunha boa corrección.

A revisión posterior usa Qwen3 de 8B, con criterios máis explícitos. Hai unha exportación versionada `corpus_ai_revised.jsonl`: conserva texto, autoría e etiqueta anterior, move as revisións humanas orixinais ao historial e identifica o novo obxectivo como IA non confirmada. Este ficheiro non substitúe o corpus humano nin se usa como referencia de exactitude humana.

## Ferramentas reproducibles

Os comandos execútanse desde a raíz do repositorio. Os directorios de saída deben ser novos. Os datos e os pesos privados quedan fóra de Git.

```powershell
python -m hydra.training.decision_balanced_examples --out RUTA_NOVA_SINTETICOS
python -m hydra.training.decision_teacher --corpus CORPUS_REVISADO.jsonl --out RUTA_NOVA_PROPOSTAS --model hydra-instruction-v8:latest --single
```

`scripts/train_balanced_synthetic.py` adestra a receita que conserva as etiquetas reais. `scripts/train_teacher_candidates.py` compara as dúas variantes das propostas. Ambos reciben `--original`, `--revised`, `--reviewed-root`, `--baseline-root`, `--synthetic`, `--checkpoint` e `--out`; o segundo require tamén `--teacher-root` completo e verificado. `--help` describe os argumentos. O entorno usado debe ter o encoder real dispoñible.

## Continuación e condición de promoción

1. Completar as propostas para todas as preguntas; rexistrar discrepancias e distribución por clase sen substituír confirmacións humanas.
2. Medir os candidatos coa mesma referencia e publicar por separado exactitude humana e concordancia coa IA. Un 90 % de concordancia coa IA non é un 90 % de acerto humano.
3. Axustar só coas particións de desenvolvemento e calibración, priorizando familias diversas de `tool_use`, `abstain`, `privacy` e `security`. Máis repeticións de frases non substitúen diversidade.
4. Cando exista un candidato prometedor, validar cun lote humano novo reservado antes do axuste: exactitude, macro-F1 das dez clases, recall crítico, cobertura e calibración. Se non alcanza o obxectivo humano do 90 %, continúa en observación.
5. Integrar no motor só despois da validación humana final, con versión anterior recuperable. O calibrador, os exemplos e a procedencia son exportables sen depender de Lovable.

Probas locais actuais: 36 comprobacións das propostas, particións, revisión humana, comparación, aprendizaxe continua, interface e avisos de autoría. Ruff pasa nos ficheiros novos.

A proba real do motor e os axentes, a preparación do encoder e a corrección da independencia dos votos constan en [HYDRA_HYD_REAL_2026-10-05.md](HYDRA_HYD_REAL_2026-10-05.md).
