# Cómo validar tus casos

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Abre http://127.0.0.1:18086/hydra/v1/evaluation/review y escribe tu nombre. Hay 300 casos recibidos en archivos, correspondientes a 287 preguntas únicas. Los duplicados se señalan y cuentan una sola vez en la medida de precisión independiente. Tus primeros 50 casos enviados en el mensaje constituyen otro bloque de referencia; no se mezclaron automáticamente con estos archivos, cuyos IDs empiezan también en 1, para evitar sobrescribir preguntas distintas.

1. Lee la pregunta. Identifica qué pide y si impone un formato, una cantidad de palabras o un orden.
2. Mira la referencia y después la respuesta real del modelo. Esta pantalla muestra respuestas del GGUF v5 sin intervención del solucionador de HYDRA.
3. Marca **Correcta** si cumple la tarea y el formato. En una definición, otras palabras pueden expresar correctamente la misma idea.
4. Marca **Incorrecta** si falla el resultado, inventa datos, pierde elementos, incumple el formato obligatorio o no responde a la tarea.
5. Marca **Ambigua** si la pregunta permite varias respuestas razonables y la referencia no explica cuál se acepta. Escribe el motivo. No cuentes como fallo que una respuesta válida use un sinónimo.
6. Pulsa **Guardar y siguiente**. Puedes volver a un caso para cambiar tu valoración. **Descargar mi revisión** exporta tus decisiones.

## Ejemplos concretos

- En una ordenación, compara los valores, el orden y las repeticiones: `[4,4,9,12]` conserva los dos cuatros; `[4,9,12]` pierde uno y es incorrecto.
- En JSON, el orden de claves y los espacios no importan. `false` es booleano; `"false"` es texto y no satisface una petición de booleano. `12000000000` y `12e9` representan el mismo número si la petición no exige una escritura concreta.
- Si se pide “solo la suma”, `20` es correcto; una explicación adicional incumple ese formato.
- En “El evaluador debe ser ______”, pueden ser razonables “imparcial”, “neutral” u “objetivo”. Si no se concreta la intención, marca **Ambigua** y anota las alternativas aceptables.
- En definiciones, no compares letra por letra: comprueba la idea y la veracidad. Una definición de MoE debe explicar que se usan expertos especializados y que se activa una parte según la entrada; no exige que todos los expertos generen respuestas completas.
- Cuando se ordena por longitud y hay empates, mantener el orden original es válido salvo que se indique un segundo criterio. No penalices un empate por falta de criterio en la referencia.

La coincidencia automática es una ayuda, nunca tu valoración. No todos los casos son respuestas únicas: completar huecos abiertos y definir conceptos necesitan juicio humano. Los ambiguos se mantienen visibles y no se eliminan silenciosamente para subir la puntuación. Las referencias se conservan congeladas, aunque tu nota cuestione una; la corrección de una referencia necesitaría una nueva versión del test.

El selector **Origen de las preguntas** permite declarar si fueron redactadas por personas, con ayuda de IA, por IA o si no lo sabes. Marca lo que corresponda y pulsa **Guardar origen declarado**. No se presupone autoría humana y el modelo no puede declararla por ti.

## Qué todavía no demuestra esta revisión

El origen de los prompts se registra como **aportados por el usuario**, sin suponer quién los redactó. Una valoración humana no convierte texto generado por IA en texto de autoría humana. El conjunto no entró en entrenamiento y su SHA256 se vincula a las respuestas y a cada revisión.

Completar la revisión no promociona automáticamente el modelo. `scripts/check_instruction_certification.py` comprueba calidad, identidad de artefactos, estabilidad y revisión humana, y deja explícitos los requisitos pendientes. Un test con tareas relacionadas tampoco certifica conocimiento general, seguridad, visión o todos los usos futuros.
