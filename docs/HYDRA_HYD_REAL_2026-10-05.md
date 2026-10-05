<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Proba real de HYDRA con Hyd e os axentes

Executouse `scripts/probe_hydra_hyd.py` co motor real, o candidato Hyd equilibrado con sintéticos, MiniLM cargado na GPU e modelos locais de Ollama. Non se empregou un proveedor simulado. Os casos son sintéticos e non constitúen un benchmark humano do corpus.

Cada execución usa un directorio novo, memoria SQLite propia, ferramentas nun espazo temporal e `shadow=True, learn=False`. Non escribe en PostgreSQL nin modifica o corpus, a configuración activa ou o modelo promovido. Hyd está conectado como observador; a súa política non pasou, polo que abstén e non substitúe a ruta de autoridade.

## Resultados observados

- Co modelo de instrucións v8, o cálculo de doce caixas de tres pezas e seis pezas soltas deu **24**. O resultado correcto é **42**. A proba rexistrou o fallo.
- Co Qwen3 de 8B, o mesmo cálculo deu **42**, cunha explicación que suma 36 e 6.
- O axente de código chamou realmente a `filesystem.read` e devolveu o contido exacto do ficheiro de proba. Non se acepta unha lista de ficheiros imaxinada como proba de lectura.
- As trazas desta sesión inclúen chamadas reais de razoamento, crítica, xuízo, síntese e código. Nunha execución Qwen3 úsanse varios nomes lóxicos para o mesmo modelo físico; isto proba a orquestración dos roles, non independencia entre modelos.
- Hyd esgotou inicialmente o límite de cinco segundos ao cargar o encoder en frío. Co encoder preparado antes das peticións, as observacións medidas quedaron arredor de 16–66 ms nos tres casos da execución v8 en quente. Son mostras, non percentís de latencia.

## Melloras derivadas da proba

O bootstrap prepara o encoder MiniLM dos candidatos antes de recibir peticións e rexistra `encoder_ready`. Se a caché falta, informa dun estado degradado e mantén o arranque dispoñible. Non cambia os pesos nin os hashes da implementación dos rankers previamente adestrados.

Dous nomes distintos co mesmo modelo físico, ou coa mesma familia declarada, deixan de contar como verificación independente. As súas aprobacións non acreditan a resposta; os achados negativos consérvanse e o acordo conta unha resposta por familia. As ferramentas e as comprobacións matemáticas poden fornecer evidencia propia.

Isto evita dar por verificada unha resposta só porque un modelo repetiu a súa propia opinión con dous nomes. Non demostra que todas as respostas sexan correctas.

## Reprodución

```powershell
python -m scripts.probe_hydra_hyd --candidate RUTA_CANDIDATO --out RUTA_NOVA --model qwen3:8b
```

Require o encoder real dispoñible no entorno e o modelo local instalado. O informe privado garda respostas, eventos, roles, observación de Hyd, identidade do modelo e comprobación do ficheiro de proba. A política de promoción segue sen superar o criterio; o obxectivo do 90 % humano permanece pendente.

Verificación final: a suite completa de HYDRA pasou **1.178 probas / 83 omitidas** e a de Hyd pasou **1.274 / 87 omitidas**. As omisións corresponden a dependencias ou condicións non dispoñibles. Outras 55 comprobacións afectadas tamén pasaron. Ruff pasa nos ficheiros modificados. A evidencia pública da última proba real está en `docs/evidence/hydra-hyd-real-smoke-2026-10-05.json`.

GitHub executou parte das comprobacións, pero cancelou outros jobs coa anotación «The job was not acquired by Runner of type hosted even after multiple attempts». Eses jobs non executados non contan como probas superadas.
