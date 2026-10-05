<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->

# Export privado de Lovable: comprobación local

Data: 5 de outubro de 2026. O ZIP v2 descargouse localmente desde unha ligazón
temporal do almacén privado. A ligazón e os datos privados non se gardan neste repo.

SHA-256 comprobado: `76f845a373e0ab9e4055791ca5649c621795e94b24b0d83227c45a1c34705c95`.
Os 135 ficheiros están cubertos exactamente polo manifesto e todos os hashes
coinciden. Hai 168 entradas ZIP incluíndo directorios e manifesto. Ningunha ruta
insegura, duplicada, ligazón simbólica nin entrada cifrada foi admitida.

## Resultados medidos

| Comprobación | Resultado |
|---|---:|
| Preguntas JSON e CSV, idénticas por ID/texto | 6.236 |
| Consentimento explícito con texto | 6.236 |
| Hashes do texto orixinal correctos | 6.236 |
| Anotacións con referencia/texto correctos | 750 |
| Cola vinculada ás correccións sospeitosas | 86 |
| Cola pendente / revisada | 82 / 4 |
| Anotacións seleccionadas para avaliación | 0 |
| Anotacións pendentes no export principal | 750 |
| Preguntas coa marca de train filtrado | 2.077 |
| Dereitos verificados / procedencia declarada no export | 0 / 0 |
| Identidade independente verificada no export | 0 |

Os recontos medidos cadran co manifesto. As catro reconfirmacións figuran na conta
nova; os pseudónimos de confirmador e propietario cadran. A cola garda unha
declaración de revisión, non unha proba independente de identidade humana. Non se
converte automaticamente en selección ou etiqueta do corpus principal.

O export principal usa `hyd-human-annotation/1-export`, que non é o evento estrito
`hyd-human-annotation/1` do calibrador. Conservar a cola e as opinións existentes;
crear eventos mediante unha revisión explícita ligada ao hash do texto. Non
atribuir valores humanos orixinais ás 86 marcas modificadas: eses valores faltan.
Non converter `unsure` nin ausencia de marca en negativos.

O consentimento non substitúe dereitos/procedencia. O usuario declarou previamente
que introduciu datos propios con varias contas; esa declaración non se estende
automaticamente ás contas novas nin enche familias inexistentes. A marca de train
filtrado é histórica, non a admisión actual. A integridade do ZIP tampouco acredita
que as preguntas sexan variadas, independentes ou aptas para adestramento.

## Ferramenta reproducible

Desde o checkout de Hyd, executar nunha liña (escoller un OUT novo):

```powershell
python -m hyd_calibrator.export_bundle PRIVATE_ZIP --sha256 76f845a373e0ab9e4055791ca5649c621795e94b24b0d83227c45a1c34705c95 --audit-lovable --output OUT.json
```

Non extrae nin executa contidos, non cambia filas e o informe só contén agregados.
Rexeita hashes, cobertura do manifesto, referencias e seleccións pendentes
incorrectas; conserva `training_approved=false` e `human_reference_approved=false`.
A comprobación de integridade admite manifestos con `files` como mapa ou lista
`{path, sha256}`. Outro esquema require revisión explícita do adaptador.

Evidencia local: `.codex-artifacts/lovable-sync-20261005/audit-v2.json`.
Evidencia agregada no repo: `evidence/lovable-export-local-audit-20261005.json`.
As probas usan pequenos fixtures artificiais de seguridade e contratos; os recontos
anteriores proveñen da execución sobre o ZIP real, non dos fixtures.

## Continuidade do plan

Fase 1: integridade e contido local verificados. A recuperación segue incompleta
respecto do historial humano perdido, predicións/probabilidades E2/E3 por fila,
pesos/calibracións dos experimentos independentes e revisión exacta do encoder.
Non reconstruír eses datos a partir de resultados agregados. Existe unha cabeza
semántica histórica no repo; non acredita a reprodución dos experimentos perdidos.

Fase 2: completar declaracións de orixe, dereitos, persoas/familias e revisións
reais. As reconfirmacións aínda non están seleccionadas como referencia E3.
O usuario confirmou nesta sesión que Juan e a conta nova pertencen a outras
persoas. Rexístranse tres persoas declaradas: propietario (2.936 preguntas),
externa A (1.000) e externa B (2.300), mantendo as dúas contas do propietario
xuntas. Isto non modifica o export orixinal nin acredita identidade independente.
Hai unha plantilla privada ligada aos IDs/hashes para completar familias e orixe.
Con tres persoas non se poden poboar catro particións non baleiras separadas por
persoa. Recoller máis autores ou fixar outro protocolo explícito; non crear persoas
ficticias nin chamar independente a unha división aleatoria das mesmas persoas.
Declaración agregada: `evidence/lovable-person-declarations-20261005.json`.
Fase 3: particións por grupos e test novo reservado, sen reutilizar resultados
históricos como test cego. Despois reproducir E2 con revisión fixada e artefactos
persistentes. Non se executou un novo adestramento nin se promoveu ningún modelo.

A rama `lovable/evaluator-app-20261005` recibiu o código da cola en `09f2678`;
PR #8 conserva o snapshot como borrador. A exportación do código non equivale a
unha app independente: quedan revisión de build/auth, portabilidade e cabeceiras
do snapshot. A conexión Git nativa bidireccional non se configurou.
