# Plan de mejora de Kev para HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 30/09/2026. Este plan parte de la evaluación real en CUDA y conserva el
modo `KEEP_SHADOW` hasta cumplir los controles. No convierte una confianza del
modelo en permiso de herramienta.

## Diagnóstico que guía el trabajo

Kev acertó 20/24 casos de prueba, con límite inferior Wilson del 64,1 %. El ECE
fue 0,3859 y el Brier 0,3424. Un umbral de probabilidad 0,5 aceptó todos los
casos. El umbral selectivo obtuvo 11/11 aciertos, pero solo cubrió el 45,8 % y
su límite inferior fue 74,1 %. Al invertir el orden de opciones, el acuerdo fue
91,7 %. La estabilidad de 120 segundos dio 176 solicitudes, cero errores, p50
44,4 ms y p95 384,9 ms. El conjunto es pequeño y escrito por nosotros; no es
una certificación de calidad general.

El objetivo es mejorar cuatro propiedades por separado: clasificación, calibración,
invarianza al orden y disponibilidad bajo carga. Un cambio solo se conserva si
mejora el test congelado y no empeora las regresiones, la latencia o la abstención.

## Fase 0 — Protocolo y baselines (1 día)

Implementación inicial: `decision-corpus-v3` ya contiene 1.600 filas de
entrenamiento, 200 de calibración y 1.000 de test repartidas en diez familias.
Cada fila lleva hash, procedencia, permiso y familia. Su contenido sigue siendo
sintético y requiere revisión humana antes de usarlo para ajustar pesos.

1. Congelar `decision-benchmark-v3`: 200 casos de calibración, 1.000 de prueba
   y 200 OOD. Mantener al menos 100 casos por `chat`, `coding`, `reasoning`,
   `research`, `vision`, `tool_use`, seguridad, privacidad y abstención.
2. Dividir por familia, plantilla, idioma, origen y paráfrasis. Ningún caso de
   test puede compartir texto, plantilla o solución con entrenamiento.
3. Añadir baselines: reglas actuales, clasificador HYDRA n-gram y Kev. Medir
   accuracy, macro-F1, matriz de confusión, Brier, log-loss, ECE, cobertura/error
   selectivo, acuerdo con permutación y latencia p50/p95/p99.
4. Publicar hashes del corpus, protocolo, modelo, configuración y servidor.

Salida: informe que permita saber si una mejora procede de los datos, de la
calibración o de la configuración. El test queda bloqueado antes de tocar pesos.

## Fase 1 — Corpus HYDRA de decisiones (3–5 días)

Resultado de la primera ejecución v3: las 1.200 solicitudes se procesaron sin
errores, pero la cabeza Kev solo devolvió etiquetas compatibles en 600/1.000
casos de test. La siguiente iteración debe ampliar el contrato y las etiquetas
antes de interpretar la cobertura como calidad.

Crear 2.000 ejemplos admitidos antes de entrenar: 1.200 casos normales, 400
difíciles/ambiguos y 400 OOD/abstención. Para cada ejemplo guardar texto, etiqueta
correcta, opciones en dos órdenes, severidad, idioma, procedencia, permiso de
entrenamiento y verificador. La mitad debe ser paráfrasis humana o revisada; no
generar todo con un LLM.

Incluir pares mínimos: cambiar una sola palabra entre `chat` y `tool_use`, una
imagen presente/ausente, una solicitud de investigación con/sin fuentes, y
peticiones de alto riesgo que deben producir `review` o abstención. Incluir
errores tipográficos y español de España/LatAm. Los negativos solo entran si
existe una etiqueta explícita y una razón verificable.

Particionar por familia y reservar el test. Deduplicar por hash normalizado y
similitud; revisar manualmente los conflictos. Rechazar filas sin licencia,
procedencia o `training_allowed=true`.

Salida: `decision-corpus-v3` con manifiesto, informe de derechos y catálogo de
errores. No usar las trazas reales del test para corregir el entrenamiento.

## Fase 2 — Calibración sin modificar Kev (1–2 días)

Implementado en esta iteración: `TemperatureCalibrator` aplica temperatura como
artefacto externo y `fit_temperature` selecciona por NLL únicamente sobre filas
de calibración. El observador puede recibir ese calibrador sin cambiar los pesos.
El artefacto exige el hash del dataset de calibración y conserva la distribución
original para auditoría. Aún no se ha aplicado al resultado real de Kev; primero
hay que ajustar con el corpus v3 ampliado y medir el test congelado.

Usar solo la partición de calibración para ajustar temperatura por clase o una
calibración isotónica/Platt sobre las probabilidades de Kev. Guardar el calibrador
como artefacto separado con hash y versión; no reescribir las probabilidades
originales. Evaluar después en el test congelado.

Elegir el umbral mediante coste explícito: una ruta errónea de herramienta cuesta
10, una revisión humana 1 y una abstención normal 0,5. El umbral debe optimizar
riesgo esperado con una restricción de cobertura, no exigir 95 % en un conjunto
pequeño. La promoción mínima provisional es ECE ≤0,10, Brier al menos 20 % menor,
límite inferior selectivo ≥0,90 y cobertura ≥0,60.

Si ningún umbral cumple, Kev solo puede informar `uncertain`; el router conserva
las reglas. Las clases `tool_use`, seguridad y privacidad requieren un umbral más
alto y verificación independiente.

## Fase 3 — Invarianza y configuración (2–3 días)

Implementado en esta iteración: el cliente ordena de forma determinista las
opciones `choice` antes de enviarlas y remapea las probabilidades a la orden del
contrato al volver. Las respuestas siguen pasando la validación exacta. Esto
elimina una fuente de variación del protocolo; no oculta una variación interna
del modelo, que se seguirá midiendo con pares permutados.

Ejecutar una matriz A/B con semilla, temperatura, `KEV_PREFIX_CACHE`, tamaño de
lote, contexto máximo, orden de opciones y `KEV_CUDA_GRAPHS`. Medir cada cambio
por separado para no atribuir una mejora al componente equivocado.

El contrato HYDRA debe canonicalizar el orden de opciones antes de enviar la
consulta y remapear la respuesta al orden original. Probar que la permutación no
cambia la etiqueta ni la distribución remapeada. Si el modelo cambia realmente
con el orden, registrar discrepancia y abstenerse; no ocultarla ordenando después.

Objetivo: acuerdo ≥99 % en 1.000 pares permutados, cero respuestas malformadas,
calentamiento separado de la medición y p95 ≤500 ms en dos solicitudes concurrentes.

## Fase 4 — Ajuste de pesos, solo si hace falta (1–2 semanas)

Primero entrenar una cabeza/clasificador HYDRA con el corpus admitido y comparar
contra Kev congelado. Solo si no alcanza los objetivos, evaluar un ajuste LoRA
pequeño sobre la base Qwen compatible, con dos semillas y una mezcla 70 % tareas
tipadas, 20 % abstención/seguridad y 10 % invariancia de opciones.

No mezclar las tareas generativas de `HYDRA.gguf` con la cabeza de decisiones.
Conservar el checkpoint Kev original, adaptador, receta, semillas y hashes.
Parar si cae una clase crítica más de 2 puntos, aumenta ECE o empeora OOD.

## Fase 5 — Estabilidad y canary (1 semana)

Ejecutar 24 horas y al menos 1.000 tareas con concurrencia 1, 2 y 4. Registrar
errores, timeouts, reinicios, VRAM/RAM, p50/p95/p99, cola y respuestas repetidas.
Probar caída del proceso, servidor ocupado, pérdida de red local, memoria llena y
cancelación. El fallback debe producir la misma decisión de reglas y dejar un
evento auditable.

Solo después hacer canary del 5 % en tareas `chat` y `research` de bajo riesgo.
Excluir `tool_use`, seguridad, privacidad, dinero, médico y legal. Durante canary
Kev propone; las reglas y la política deciden. Rollback automático ante cualquier
error de esquema, fuga de permisos, p95 >500 ms durante 5 minutos o descenso de
calidad superior a 2 puntos.

## Puerta de promoción

Kev podrá pasar de observador a proponente limitado únicamente si se cumplen todos:

- ≥1.000 casos de test congelados; límite inferior de accuracy macro ≥0,90.
- ECE ≤0,10 y Brier/log-loss mejor que Kev sin calibrar.
- Cobertura selectiva ≥0,60 con límite inferior ≥0,90.
- OOD y alto riesgo siempre abstienen o solicitan revisión; nunca autorizan.
- ≥99 % de invariancia a orden y ≥99 % de respuestas de esquema válidas.
- 24 h / 1.000 tareas, <1 % errores inesperados y rollback probado.
- Cero decisiones de permisos delegadas al modelo.

Si falla una sola puerta, el estado vuelve a `KEEP_SHADOW` y se documenta la causa.
La mejora del modelo generativo Q5 se evalúa por separado; sus resultados no se
usan como evidencia de calibración de Kev.
