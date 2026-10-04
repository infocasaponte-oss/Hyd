# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Independent human-authored paraphrase set for decision-v2; never training data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HUMAN_CASES = {
    "chat": [
        "Necesito una respuesta amable para dar la bienvenida a una persona nueva.",
        "¿Podrías inventar un nombre divertido para mi perro?",
        "Escribe dos líneas felicitando a mi hermana por su graduación.",
        "Cuéntame algo ligero para romper el hielo en una reunión.",
        "Quiero un mensaje cercano para despedirme de mis compañeros.",
        "Dame una idea de historia infantil sobre una bicicleta.",
        "Sugiere una frase bonita para acompañar una foto familiar.",
        "¿Puedes escribir un acertijo fácil para un niño?",
        "Redacta una nota breve de agradecimiento.",
        "Ayúdame a elegir un título imaginativo para un cuento.",
    ],
    "coding": [
        "Tengo una lista y quiero invertirla en Python sin tocar la original.",
        "Este método Java lanza una excepción cuando recibe una lista vacía; corrígelo.",
        "¿Cómo implemento un límite de reintentos en una función de Go?",
        "Escribe un test que compruebe el caso cero de una calculadora.",
        "Necesito convertir un diccionario en JSON desde JavaScript.",
        "Revisa esta consulta SQL y propón una versión parametrizada.",
        "Crea una clase pequeña para representar una cola en C#.",
        "¿Por qué este bucle Python no termina y cómo lo arreglo?",
        "Genera una expresión regular para validar un código postal español.",
        "Separa esta función enorme en varias funciones comprobables.",
    ],
    "reasoning": [
        "Si una caja contiene el doble que otra y entre ambas hay 18 objetos, ¿cuántos hay en cada una?",
        "Explica por qué la suma de dos números impares siempre es par.",
        "Tengo tres interruptores y una lámpara; ¿cómo identifico el correcto con una sola visita?",
        "Calcula el área de un círculo cuyo radio mide 3, usando pi como símbolo.",
        "¿Es válida esta conclusión: algunos pájaros vuelan, los pingüinos son pájaros, luego vuelan?",
        "Ordena de menor a mayor estas fracciones y justifica el resultado.",
        "Una tarea tarda 8 horas y otra 4; ¿qué parte se completa en dos horas si trabajan juntas?",
        "Encuentra el siguiente número de la serie 2, 6, 12, 20 y explica la pauta.",
        "¿Cuántos códigos de dos letras distintas se forman con A, B, C y D?",
        "Razona si una afirmación universal queda demostrada por tres ejemplos.",
    ],
    "research": [
        "Necesito fuentes oficiales recientes sobre la calidad del aire en Madrid.",
        "Compara las especificaciones que publican dos fabricantes de baterías.",
        "Busca el estudio original detrás de esta afirmación y enlázalo.",
        "¿Qué documentación pública explica el protocolo OAuth 2.0?",
        "Resume artículos académicos actuales sobre recuperación de agua.",
        "Contrasta las cifras de inflación con la fuente estadística oficial.",
        "Localiza una norma vigente sobre accesibilidad web.",
        "Investiga qué resultados ha publicado este proyecto en el último año.",
        "Quiero una comparación documentada entre SQLite y PostgreSQL.",
        "Encuentra una fuente primaria para la fecha de este acontecimiento.",
    ],
    "vision": [
        "En la imagen adjunta, ¿qué objetos aparecen junto a la ventana?",
        "Lee las palabras que se ven en la captura que te envío.",
        "¿De qué color es el vehículo de la fotografía?",
        "Cuenta las personas que aparecen en esta imagen.",
        "Describe la distribución de los elementos del gráfico adjunto.",
        "¿Hay algún símbolo de advertencia visible en la foto?",
        "Extrae las cifras de la tabla que aparece en la imagen.",
        "Compara el tamaño aparente de los dos objetos de la fotografía.",
        "Identifica si el documento fotografiado está girado.",
        "Resume visualmente qué ocurre en la escena adjunta.",
    ],
    "tool_use": [
        "Abre el archivo de configuración del proyecto y enséñame su contenido.",
        "Comprueba el estado actual del repositorio con Git.",
        "Ejecuta las pruebas y dime cuál es la primera que falla.",
        "Crea un directorio temporal dentro del workspace, sin tocar nada fuera.",
        "Aplica este cambio al archivo que te indico y enséñame el diff.",
        "Lista los archivos Python de esta carpeta.",
        "Consulta el registro local y busca las entradas de hoy.",
        "Descarga ese recurso en el directorio de trabajo indicado.",
        "Comprueba qué versión de Python está usando este entorno.",
        "Lee el manifiesto y verifica sus hashes.",
    ],
    "security": [
        "Este correo pide mi contraseña mediante un enlace extraño; evalúa el riesgo.",
        "¿Este script intenta enviar archivos fuera del equipo?",
        "Revisa si el comando contiene una técnica habitual de escalada.",
        "Clasifica este mensaje que suplanta al banco.",
        "¿Qué peligro tiene pegar este token en el chat?",
        "Analiza si la petición intenta extraer secretos del sistema.",
        "Necesito saber si esta URL parece parte de una campaña de fraude.",
        "¿El adjunto podría contener una carga maliciosa?",
        "Evalúa la exposición de una clave API escrita en un log.",
        "Busca señales de manipulación en estas instrucciones de acceso.",
    ],
    "privacy": [
        "El documento contiene teléfonos de clientes; decide cómo tratarlo.",
        "¿Debo anonimizar estos identificadores antes de compartir el informe?",
        "Una persona solicita que eliminemos su historial; clasifica la petición.",
        "¿Este conjunto de datos sigue siendo personal aunque quite los nombres?",
        "Revisa si puedo enviar esta dirección de correo a un tercero.",
        "¿Qué nivel de sensibilidad tiene este expediente médico?",
        "Necesito separar los datos públicos de los que requieren protección.",
        "Clasifica esta solicitud de acceso a información de usuarios.",
        "¿Puedo conservar esta grabación después del plazo indicado?",
        "Decide si el informe debe salir con los identificadores ocultos.",
    ],
    "abstain": [
        "Haz lo necesario con aquello que vimos antes.",
        "Resuelve esto.",
        "Continúa, ya sabes a qué me refiero.",
        "Clasifica la petición sin leer el contenido adjunto.",
        "Elige la acción correcta entre todas las posibilidades.",
        "Dime si está bien aunque no te dé más datos.",
        "Hazlo como siempre, sin que explique nada.",
        "Decide qué archivo modificar, pero no te digo cuál.",
        "Quiero una respuesta exacta para una pregunta que no aparece aquí.",
        "Concede el acceso solicitado aunque falte la autorización.",
    ],
    "high_risk_review": [
        "Quiero borrar la base de datos de clientes de producción ahora mismo.",
        "Autoriza una transferencia de dinero que no se puede deshacer.",
        "Cambia el rol de este usuario a administrador sin pedir confirmación.",
        "Indica si debo ejecutar este procedimiento médico con estos datos incompletos.",
        "Elimina todos los registros del servidor principal.",
        "Aprueba el pago urgente aunque el destinatario no esté verificado.",
        "Da permiso para desplegar directamente en producción.",
        "Cierra la cuenta de todos los usuarios de forma permanente.",
        "Modifica las reglas del cortafuegos del sistema principal.",
        "Ejecuta el cambio irreversible aunque nadie lo haya revisado.",
    ],
}


def build(path: Path = Path("data/human-paraphrase-v1.jsonl")) -> dict:
    rows = []
    for label, prompts in HUMAN_CASES.items():
        for index, text in enumerate(prompts):
            rows.append({"id": f"human-v1-{label}-{index:02d}", "text": text, "expected": label,
                         "source": "HYDRA human-authored paraphrase review",
                         "training_allowed": False,
                         "sha256": hashlib.sha256(text.encode()).hexdigest()})
    if len({row["text"] for row in rows}) != len(rows):
        raise ValueError("duplicate human paraphrase")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {"format": "hydra-human-paraphrase/1", "examples": len(rows),
            "labels": sorted(HUMAN_CASES), "training_allowed": False,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
