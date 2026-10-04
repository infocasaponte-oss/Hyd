# Kev: calibración y estabilidad

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Fecha: 30/09/2026. Evaluación contra el servidor real Kev en CUDA, checkpoint
fijado. El conjunto contiene 24 casos de calibración, 24 de prueba y 8 casos
ambiguos/fuera de alcance. Ninguno se admite como dato de entrenamiento.

Resultado de calidad:

- Calibración: 21/24, 87,5 %. ECE de 10 cubetas: 0,3035; Brier: 0,2594.
- Prueba independiente: 20/24, 83,3 %. Límite inferior Wilson al 95 %: 64,1 %.
- Umbral elegido solo con calibración: probabilidad máxima 0,5.
- Con ese umbral, la prueba aceptó 24/24; no alcanza la precisión objetivo.
- El modo selectivo aceptó 11/24 (45,8 %) con 11/11 correctos; su límite
  inferior Wilson es 74,1 %, por debajo del 90 % requerido.
- Casos ambiguos/OOD aceptados: 0/8.

Estabilidad real:

- 176 solicitudes en 120 segundos, dos concurrentes por tanda.
- Errores de servicio: 0.
- Latencia p50: 44,4 ms; p95: 384,9 ms; dos solicitudes superaron 500 ms.
- Acuerdo al repetir y cambiar el orden de opciones: 91,7 %.
- GPU muestreada durante la prueba; el proceso Kev se mantuvo cargado en CUDA.
- No se ha ejecutado todavía una prueba de 24 horas.

La conclusión es **KEEP_SHADOW**. Kev no recibe control del router, permisos,
herramientas ni decisiones finales. La inestabilidad al permutar opciones y la
calibración insuficiente hacen inseguro usar su confianza como autorización.
El router determinista sigue siendo la decisión efectiva y puede usar esta
salida como evidencia experimental.

El siguiente hito exige ampliar el conjunto independiente a al menos 200 casos,
recalibrar con datos separados, repetir por idioma y medir abstención. Después
se podrá hacer un canary solo para tareas de bajo riesgo, con fallback y sin
conceder permisos. La promoción requiere además el ensayo sostenido de 24 horas.

Evidencia completa: [kev-calibration-stability.json](evidence/kev-calibration-stability.json).
El burst inicial se conserva en [kev-calibration-burst.json](evidence/kev-calibration-burst.json).
