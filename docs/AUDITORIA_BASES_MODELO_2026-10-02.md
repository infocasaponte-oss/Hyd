<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Auditoría de bases de modelo y diseño de HYDRA Base V1

Fecha: 2 de octubre de 2026. Objetivo: decidir si HYDRA entrena una base propia desde cero, qué tomar de cada familia de modelos abiertos de primer nivel y cómo escalar por etapas (local → nube) sin descartar un modelo grande más adelante.

## 1. Resumen de la decisión

- **Producción ahora:** seguir con la línea actual, ajuste LoRA sobre Qwen2.5-Coder-1.5B. Funciona, cabe en la RTX 3060 Ti y el candidato anclado a fuente ya da 141/154 frente a 88/154 de su base.
- **En paralelo:** construir **HYDRA Base V1**, con pesos y tokenizador propios, empezando pequeña (30M → 125M) en local y escalando a la nube solo cuando cada etapa cumpla sus objetivos medidos.
- **No tomar una familia entera, sino una receta.** La arquitectura y el entrenamiento combinan lo que cada familia ha demostrado: el diseño estándar compatible con llama.cpp, la receta abierta de SmolLM3/OLMo, la forma profunda y estrecha de MobileLLM para menos de 1B, el optimizador Muon, el tokenizador propio y, más adelante, la destilación al estilo Ministral y el MoE de DeepSeek y Qwen para escalar.

## 2. ¿Por qué Qwen y no Mistral, Llama o Gemma para la línea actual?

La elección se hizo con restricciones concretas: ajuste LoRA en 8 GiB, licencia permisiva, buen código y español, y soporte en llama.cpp.

| Familia | Tamaños pequeños disponibles | Licencia | Encaje con HYDRA hoy |
|---|---|---|---|
| **Qwen** (2.5 → 3.5) | 0,5B–9B; Qwen3.5 Small: 0,8B/2B/4B/9B | Apache-2.0 | El mejor encaje a 1,5B: código fuerte, multilingüe, LoRA en 8 GiB comprobado en este repo |
| **Mistral / Ministral 3** | 3B, 8B y 14B (diciembre de 2025) | Apache-2.0 | Bueno, pero el más pequeño es 3B; en 8 GiB solo con QLoRA, que no está demostrado aquí ([PLAN_MAESTRO](PLAN_MAESTRO_HYDRA_MULTIMODELO.md)) |
| **Gemma 4** | E2B, E4B, 12B, 26B MoE y 31B | Apache-2.0 desde Gemma 4 (antes, términos propios) | Candidato serio para la siguiente evaluación comparativa |
| **Llama 4** | Sin tamaños pequeños de última generación | Licencia comunitaria: los derivados deben llevar «Llama» al inicio del nombre, «Built with Llama» obligatorio y restricciones para domiciliados en la UE | **Descartado:** choca con que HYDRA sea el nombre público y con la residencia en la UE |
| **DeepSeek** (V3/R1) | Solo destilados; los propios son MoE enormes | MIT | Fuente de ideas para escalar (MoE, MLA, MTP, FP8), no de base pequeña |

Conclusión: Qwen no fue «el mejor modelo», sino el que mejor cumplía 1,5B + Apache-2.0 + código + español + 8 GiB. Ministral 3 y Gemma 4 son hoy alternativas legítimas para comparar como base de ajuste; Llama queda fuera por licencia.

## 3. Referentes para entrenar una base propia

| Referente | Qué demuestra | Qué tomamos |
|---|---|---|
| **SmolLM3-3B** (HF, Apache-2.0) | Receta completa publicada: GQA, NoPE en 1 de cada 4 capas, embeddings atados, AdamW + programa WSD, mezcla de datos en 3 etapas (web 85→63 %, código 12→24 %, matemáticas 3→13 %), 11,2T tokens en 384 H100 durante 24 días | Embeddings atados, sin *weight decay* en embeddings, programa WSD, currículo por etapas |
| **OLMo 3** (Ai2, Apache-2.0) | Todo abierto: datos, código, checkpoints intermedios y registros | Reproducibilidad: manifiestos y checkpoints versionados |
| **MobileLLM** (Meta) | Por debajo de 1B, la profundidad pesa más que la anchura: forma profunda y estrecha, GQA y embeddings compartidos | Forma de la red para 30M–350M |
| **Muon** (optimizador) | Hasta unos 2× de eficiencia de cómputo frente a AdamW; en modelos de 17M–202M, la mitad de FLOPs para la misma pérdida | Muon en las matrices y AdamW en embeddings y normas |
| **Puro-2B** (2026) | Una base de 1,5B (arquitectura Qwen2) entrenada en RTX 5090 por menos de 6.900 $ se acerca a Qwen2.5-1.5B | Prueba de que el escalado barato es viable |
| **Ministral 3** | Modelos pequeños obtenidos por destilación en cascada (podar y seguir entrenando con un profesor) | Etapa futura: destilar de un profesor Apache-2.0 |
| **Salamandra / ALIA** (BSC, Apache-2.0) | 2B y 7B desde cero con 7,8T tokens, con peso reforzado para español, catalán, gallego y euskera (gallego: 0,31 %) | Referencia de mezcla para español y gallego; posible profesor o comparador |
| **DeepSeek V3 / Qwen3.5 MoE** | MoE disperso, atención latente o lineal y contexto largo | Solo cuando escalemos en la nube |

## 4. Diseño propuesto de HYDRA Base V1

1. **Arquitectura:** decoder estándar tipo Llama/Qwen2 (RMSNorm, SwiGLU, RoPE, GQA, embeddings atados), para que `convert_hf_to_gguf`, llama.cpp y la evaluación actual funcionen sin cambios. Forma profunda y estrecha (por ejemplo, 125M ≈ 30 capas × 576 de dimensión). NoPE se evalúa después: hay que comprobar antes que llama.cpp lo soporta.
2. **Tokenizador propio:** BPE de 32k a 48k entrenado con nuestro corpus de español, gallego, código y BOE. Con un vocabulario de 128k–256k (Llama, Gemma), los embeddings se comerían más de la mitad de un modelo de 125M; un vocabulario propio también tokeniza mejor el español jurídico.
3. **Entrenamiento:** Muon + AdamW, programa WSD (permite seguir entrenando y escalar sin reiniciar), bf16 (la RTX 3060 Ti es Ampere: tiene bf16 pero no FP8), sin *weight decay* en embeddings y checkpoints versionados con hash.
4. **Datos por etapas:** web y texto general en español → más código y BOE → fase de enfriamiento con lo de mayor calidad. Deduplicación, filtro de calidad, la puerta de privacidad existente y procedencia por documento, como en `hydra-grounded`.
5. **Después del preentrenamiento:** el ajuste con el corpus anclado a fuente que ya tenemos, y la evaluación con exactamente los mismos tests que la línea Qwen, para comparar en igualdad.

## 5. Escalera de escalado y objetivos de paso

Cómputo de preentrenamiento ≈ 6 × parámetros × tokens; regla orientativa de unos 20 tokens por parámetro. Supuestos: unos 8 TFLOPS sostenidos en la 3060 Ti y unos 400 TFLOPS en una H100 (40 % de utilización); en Vast.ai, la H100 cuesta unos 1,5–3 $/h y la B200 unos 6,6–7,9 $/h (septiembre de 2026). Son estimaciones, no mediciones.

| Etapa | Modelo | Tokens | Dónde | Coste o tiempo estimado | Objetivo para pasar a la siguiente |
|---|---|---|---|---|---|
| 0 | 30M | ~0,6B | RTX 3060 Ti | ~4 h | La cadena completa funciona: tokenizador → preentrenamiento → ajuste → GGUF → evaluación, todo con hash |
| 1 | 125M | ~2,5B | RTX 3060 Ti | ~3 días | Perplejidad en BOE y código reservados mejor que la etapa 0; tras el ajuste, al menos el 80 % de la puntuación por hechos del candidato Qwen en las familias del corpus anclado |
| 2 | 350M–1B | 7–20B | Vast.ai, 1 H100 | 1B: ~80 h ≈ 150–250 $ | Igualar al candidato Qwen 1,5B en las tareas acotadas de HYDRA |
| 3 | 1,5–3B | 60B–1T | Vast.ai, varias H100 | 3B×60B: ~750 h H100 ≈ 1–2 k$; referencia Puro-2B < 6,9 k$ | Superar a Qwen2.5-1.5B en los tests de HYDRA → sustituir la base de producción |
| 4 | MoE o >7B | >1T | Proveedor gestionado o clúster | Decenas de k$ | Solo con objetivos de producto que lo justifiquen |

«En la nube de Claude»: Anthropic no alquila GPUs ni entrena modelos de terceros. Claude puede preparar y orquestar el entrenamiento (scripts, datos, evaluación, seguimiento), pero el cómputo tiene que venir de Vast.ai, RunPod, Lambda, AWS, GCP u otro proveedor.

## 6. Licencia propia y protección (decidido el 2 de octubre de 2026)

HYDRA Base tendrá **licencia propietaria y protegida** (borrador: [docs/legal/LICENCIA_PESOS_HYDRA_BASE.md](legal/LICENCIA_PESOS_HYDRA_BASE.md)). Esto fija los datos:

- **Admitidos** (`hydra/training/base_data_policy.py`): dominio público, CC0, CC BY, MIT, BSD, ISC, Apache-2.0, reutilización del sector público (BOE, con cita) y datos generados por HYDRA. Se conservan sus avisos de atribución.
- **Rechazados:** *share-alike* (**Wikipedia queda fuera**), *copyleft* (GPL), no comercial, «sin obras derivadas» y licencias desconocidas.
- **Profesores para destilar:** solo Apache-2.0 o MIT (Qwen3.5, Ministral 3, Gemma 4, DeepSeek); Llama no.
- **Texto general en español sin Wikipedia:** libros y prensa de dominio público (por ejemplo, Spanish-PD-Books y Spanish-PD-Newspapers de PleIAs, previa limpieza de OCR), datos abiertos del sector público con reutilización y datos sintéticos de profesores Apache-2.0.
- **Protección técnica:** los pesos nunca se publican (`models/` está fuera de git); se sirven por la API de HYDRA; los artefactos se firman (`hydra/training/signing.py`); se añade una huella (*fingerprint*) entrenada para demostrar la autoría; y el almacenamiento va cifrado y con acceso registrado.
- Los candidatos ajustados sobre Qwen **no** son HYDRA Base: conservan la licencia de Qwen.

## 7. Riesgos

- **Datos:** el BOE permite reutilización con cita; el código de Stack v2 edu viene filtrado con licencias permisivas, pero hay que conservar la atribución. Todo pasa por la política de licencias de la sección 6.
- **Regulación:** si los pesos se distribuyen, conviene preparar desde ya la documentación de datos y entrenamiento (resumen del corpus y procedencia) que exige el marco europeo para modelos de propósito general. Esto no es asesoramiento jurídico.
- **Expectativas:** un modelo de 125M no sustituye a una base general. Su valor está en ser propio, en las tareas acotadas y verificables y en servir de primer peldaño para escalar.

## Fuentes

- [Qwen3.5 Small (0,8B–9B, Apache-2.0)](https://artificialanalysis.ai/articles/qwen3-5-small-models)
- [Ministral 3 (3B/8B/14B, Apache-2.0, destilación en cascada)](https://mistral.ai/news/mistral-3/) · [informe](https://arxiv.org/pdf/2601.08584)
- [Gemma 4 (tamaños y Apache-2.0)](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/) · [historial de versiones](https://ai.google.dev/gemma/docs/releases)
- [Licencia de Llama 4](https://github.com/meta-llama/llama-models/blob/main/models/llama4/LICENSE) · [análisis de la restricción en la UE](https://dionwiggins.substack.com/p/llama-4-is-banned-in-the-eu-open)
- [SmolLM3: receta completa](https://huggingface.co/blog/smollm3) · [OLMo](https://allenai.org/olmo)
- [MobileLLM](https://arxiv.org/pdf/2402.14905) · [Muon: eficiencia práctica](https://www.alphaxiv.org/abs/2505.02222) · [Muon escalable](https://pith.science/paper/2502.16982)
- [Puro-2B en RTX 5090](https://arxiv.org/abs/2608.27370)
- [ALIA / Salamandra (BSC)](https://langtech-bsc.gitbook.io/alia-kit/modelos/modelos-de-texto)
- [Precios de Vast.ai en 2026](https://www.spheron.network/blog/vastai-pricing-2026/)
