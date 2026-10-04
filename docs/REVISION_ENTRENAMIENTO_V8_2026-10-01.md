# Revisión del entrenamiento v8

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

La receta v8 fija cuatro proyecciones q/k/v/o y LR 2e-5. La base está guardada en BF16. No se confirma que estos valores sean la causa de los fallos.

Corregido para futuras ejecuciones: exigir fin de turno supervisado, convertir parámetros entrenables FP16 a FP32 cuando CUDA no admite BF16, registrar parámetros y módulos efectivos, checkpoint seleccionado, mejor métrica y paso final. La fusión respeta el dtype de la base mediante auto y escribe merge-metrics.json.

Validación: 11 pruebas del paquete pasan; 1468 muestras reales pasan codificación. Tres conversaciones (sin system, con system y varios turnos) producen tokens idénticos con la plantilla HF y la devuelta por Ollama. Esto no certifica de forma independiente el renderizador interno de Ollama. Las 112 matrices LoRA B son no nulas; demuestra cambio numérico, no utilidad.

Preparadas cuatro recetas v9 sin reanudación: cuatro/siete proyecciones cruzadas con LR 2e-5/1e-4. Conservan base, corpus, semilla y presupuesto. No ejecutadas. Seleccionar por desarrollo y calibración, sin entrenar ni seleccionar sobre el test congelado. La diferencia de log-probabilidad base/fusionado sigue pendiente; no sustituye evaluación de respuestas ni prueba mejora por sí sola.

El GGUF v8 existente no se ha regenerado ni promocionado. Las correcciones del entrenador no cambian retroactivamente sus pesos ni evidencias.
