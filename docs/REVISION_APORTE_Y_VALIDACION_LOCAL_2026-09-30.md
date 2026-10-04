# Revisión del aporte y validación local

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

El texto adjunto es una referencia aportada por el usuario, no instrucciones ejecutables ni evidencia de validación. Su propuesta de AsyncIO y punto de entrada único coincide con HydraEngine.query. No se añade LiteLLM: HYDRA ya dispone de proveedores asíncronos y añadir una capa extra no demuestra menor tamaño o latencia.

Los siete ejemplos JSONL son útiles como borradores de SFT: soporte, extracción y ausencia de información. No son calibración probabilística. Las etiquetas de prioridad/departamento requieren política de negocio; los ejemplos con nombres, fechas y pacientes requieren confirmar que son ficticios y revisar privacidad antes de admitirlos. Generar 1000 variantes no garantiza 1000 casos independientes: se necesita diversidad de escenarios, familias separadas, validación y un test reservado. El adjunto no se ha incorporado automáticamente al corpus ni utilizado para entrenar.

El reporte de nombres incoherentes corresponde a una implementación anterior: los dos Studios comprobados anuncian únicamente hydra, hydra-fast, hydra-deep, hydra-max y hydra-private en /v1/models; el catálogo interno de backends tiene otra ruta. Estos modos no son nombres de pesos ni requieren un GGUF por cada modo.

Se implementa un observador local calibrado, vinculado por SHA256 al clasificador y al archivo de características. Se ajusta temperatura en 200 ejemplos de calibration.jsonl, sin leer test. Temperatura 0,5; NLL en esa partición de plantilla pasa de 0,018946 a 0,00005817. Es una métrica de ajuste sobre calibración, no de generalización; estado SHADOW_ONLY. La inferencia real del gateway registró esta observación en route.selected. La política determinista permanece separada y el observador no concede autorización ni decide la ruta operativa.

El GGUF Q5 servido coincide con el SHA256 634eb99a1bde8bde375206dabd0bfd45ce5be2106abe55a16dd8a49b97f8a650 del manifiesto y del archivo local. Ollama reportó el modelo cargado en GPU. Resolvió 17×19=323 pero incumplió la instrucción de salida exacta. Sigue siendo candidato.

qwen3-vl:8b identifica correctamente HYDRA 7421, el cuadrado rojo izquierdo y el círculo azul derecho en la fixture generada. Ollama reportó 5.793.780.858 bytes de modelo en VRAM. Con 128 tokens la salida quedó incompleta; con 512 respondió correctamente en 23,05 segundos, incluidos carga y evaluación. Aunque think=false llega al nivel correcto de la petición, este modelo produjo thinking en la respuesta: no se promete desactivación efectiva.

El recorrido visual inicial del gateway falló porque FAST tenía una sola llamada y percepción la consumía. Se corrige a dos llamadas para peticiones FAST con imágenes, manteniendo los límites explícitos de coste y tiempo y el preset de texto. Se valida con pruebas de regresión; el recorrido físico posterior queda registrado separadamente.

URLs locales: Studio previo en 18082 y Studio con la corrección del presupuesto visual en 18083. CeltIA ocupa 18080. No se cambia ni detiene CeltIA.

El recorrido físico corregido devuelve HTTP 200 y la descripción correcta, utiliza hydra-vision, registra dos llamadas (percepción y respuesta) y tarda 132,89 segundos. La respuesta figura como verified=false: reconocimiento correcto en una fixture no equivale a validación independiente. La latencia del motor requiere optimización. El chat añade adjunto PNG/JPEG/WebP de hasta 8 MB, enviado solo en la consulta actual; la imagen no se guarda en el historial local de mensajes.
