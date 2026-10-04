# Auditoría del paquete de fine-tuning propuesto

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Origen: `C:/Users/mejil/Downloads/files`. Fecha: 2026-10-01.

## Dictamen

Es un punto de partida útil para un candidato v8, pero no está listo para certificar ni para ejecutarlo sin adaptaciones. Se leyeron los scripts y se comprobó su sintaxis mediante AST, sin ejecutarlos. Los originales no se modificaron y no se inició entrenamiento.

## Corpus comprobado

- Entrenamiento: 168 filas, 42 por categoría.
- Validación: 32 filas, 8 por categoría.
- Total: 200 filas; coincide con la unión de entrenamiento y validación.
- No hay preguntas duplicadas ni coincidencias exactas entre ambos grupos.
- Los campos question/answer coinciden con los mensajes de usuario/asistente.
- Comparación léxica de n-gramas de cinco caracteres, umbral Jaccard 0,6: sin alertas contra las instrucciones congeladas v7, las 300 preguntas externas y las 20 preguntas de la propuesta reciente. Esto no prueba ausencia de contaminación semántica.

Los ejemplos se generan mediante plantillas y un catálogo técnico. Añadir saludos no convierte datos sintéticos en paráfrasis humanas independientes. La revisión manual declarada en los documentos no se verificó aquí.

La partición es equilibrada por categoría, pero no por habilidad: **los seis casos JSON están en entrenamiento y ninguno en validación**. Tampoco hay validación de varias otras habilidades, como ordenación descendente o extracción de números. No debe usarse todo.jsonl para entrenar porque incluye validación.

## Problemas en los scripts

### comprobar_contaminacion.py

Solo admite JSONL con question o messages; nuestros tests también usan prompt y archivos JSON. Puede fallar con archivos reales de HYDRA. La comparación léxica no detecta todas las paráfrasis. Hace falta validar entrada vacía, parámetros y separar alertas de decisiones de exclusión; no limpiar automáticamente un test congelado.

### entrenar_lora.py

La pérdida solo sobre la respuesta, la plantilla de chat y el replay son ideas adecuadas. Debe comprobar también el prefijo de IDs tokenizados: comprobar solo el prefijo del texto no garantiza la alineación. Si el truncamiento consume toda la respuesta, puede crear una fila con todos los labels en -100. Rechazar esa fila antes del entrenamiento.

El uso de device_map=auto no garantiza que el entrenamiento ocurra íntegramente en GPU. Deben registrarse dispositivo real, CUDA, memoria, identidad de la base y dependencias. Las versiones mínimas sin un entorno fijado no prueban compatibilidad con la instalación actual.

Seleccionar el mejor checkpoint por pérdida de validación es selección de modelo, **no calibración de confianza**. Es necesario un conjunto de calibración separado para cualquier umbral de decisión. Verificar que los datos de replay no incluyan validación, calibración o tests.

### evaluar_comparar.py

El evaluador no es suficiente para promoción:

- Buscar el resultado como subcadena puede aceptar 12 dentro de 120.
- La presencia del 60% de palabras clave puede aceptar una explicación falsa o negada.
- json.loads(a)==json.loads(b) admite equivalencias de Python como true==1; debe preservar tipos JSON.
- lista_n comprueba líneas y guiones, pero no que sean frutas o elementos distintos.
- Los lectores no admiten directamente nuestros registros prompt/expected_response.
- Normalizar mayúsculas puede ocultar un incumplimiento de una instrucción de mayúsculas.
- No vincula el resultado a hashes de modelos, corpus y configuración, ni verifica offload real a GPU.

La fórmula de McNemar exacta es razonable para aciertos pareados válidos, pero no corrige un evaluador defectuoso ni sustituye los controles de promoción de HYDRA.

### fusionar_adaptador.py y exportar_gguf.sh

Fusionar sobre una base no cuantizada es adecuado. Es necesario conservar y comprobar también la plantilla y configuración del tokenizador usado al entrenar.

El script de exportación es Bash y requiere adaptación para Windows. Genera nombres fijos en el directorio actual y puede sobrescribir artefactos. Debe escribir en una carpeta nueva de candidato y registrar hashes.

La cuantización propuesta por defecto es Q4_K_M; v7 es Q5_K_M. Para comparar el efecto del entrenamiento, usar inicialmente **Q5_K_M en ambos**. Una prueba de humo no demuestra estabilidad ni precisión.

El README sitúa la comparación antes de la exportación y confunde validación con calibración; corregir el orden antes de automatizar.

## Integración recomendada

1. Importar una copia con procedencia y hashes; conservar los originales.
2. Revisar referencias técnicas y ejemplos deterministas; añadir validación de JSON y habilidades ausentes sin alterar tests congelados.
3. Separar entrenamiento, desarrollo y calibración, evitando duplicados y revisando alertas semánticas.
4. Adaptar a la fábrica existente de HYDRA, usando la base HF identificada de v7 y replay solo del entrenamiento autorizado.
5. Entrenar un candidato con parámetros conservadores y evidencia real de GPU.
6. Fusionar y exportar un GGUF Q5_K_M independiente.
7. Comparar v7/candidato con idéntica configuración y evaluadores tipados; revisión humana para definiciones.
8. Ejecutar regresión, estabilidad y puertas de certificación existentes. No cambiar las valoraciones anteriores ni promover automáticamente.

Evidencia estructural y hashes de los 11 archivos: `docs/evidence/supplied-finetuning-audit-2026-10-01.json`.
