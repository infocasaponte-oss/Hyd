# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Build the 1,000-row HYDRA development paraphrase set.

This is training/development data only. The frozen human test is never read or
copied here. Templates are deliberately concentrated on known boundary pairs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

GROUPS = {
    "chat": ["Escribe una respuesta amable sobre {x}.", "Ayúdame a redactar un mensaje breve para {x}.", "Formula una frase cordial relacionada con {x}.", "Dame una respuesta sencilla y natural sobre {x}."],
    "coding": ["Corrige este código relacionado con {x}.", "Escribe una solución programática para {x}.", "Genera una función que resuelva {x}.", "Revisa la implementación de {x} y propón una mejora."],
    "reasoning": ["Resuelve paso a paso este problema: {x}.", "Deduce la respuesta a partir de estos datos: {x}.", "Comprueba lógicamente si es cierto lo siguiente: {x}.", "Explica el razonamiento necesario para {x}."],
    "research": ["Busca y compara fuentes sobre {x}.", "Investiga qué documentación fiable explica {x}.", "Resume la evidencia pública disponible acerca de {x}.", "Contrasta información y cita fuentes sobre {x}."],
    "tool_use": ["Ejecuta una acción en el entorno para {x}.", "Usa las herramientas disponibles y realiza {x}.", "Inspecciona el proyecto y haz lo necesario para {x}.", "Obtén el resultado ejecutando una operación para {x}."],
    "vision": ["Analiza la imagen y determina {x}.", "Mira el documento fotografiado para comprobar {x}.", "Interpreta el contenido visual y responde sobre {x}.", "Examina la captura y describe {x}."],
    "abstain": ["No hay suficiente información: {x}.", "Decide sin que se proporcione el contexto de {x}.", "Resuelve una petición cuyo contenido falta: {x}.", "Da una respuesta exacta aunque no se incluya {x}."],
    "security": ["Evalúa el riesgo de seguridad relacionado con {x}.", "Comprueba si {x} puede ser una amenaza.", "Analiza posibles ataques o filtraciones en {x}.", "Determina si {x} expone el sistema."],
    "privacy": ["Evalúa la privacidad de {x}.", "Determina si se pueden compartir los datos de {x}.", "Revisa el tratamiento de información personal en {x}.", "Decide si conservar o divulgar {x} respeta la privacidad."],
    "high_risk_review": ["Revisa antes de aprobar esta acción de alto riesgo: {x}.", "Solicita revisión humana para {x}.", "No ejecutes todavía; evalúa la autorización necesaria para {x}.", "Comprueba las salvaguardas antes de permitir {x}."],
}
TOPICS = {
    "chat": ["dar la bienvenida a una persona nueva", "felicitar a un compañero", "romper el hielo en una reunión", "escribir una dedicatoria", "responder a un cliente"],
    "coding": ["parametrizar una consulta SQL", "validar un código postal", "manejar errores en una API", "crear una expresión regular", "optimizar un bucle"],
    "reasoning": ["ordenar varias fracciones", "calcular cantidades desconocidas", "resolver un acertijo de interruptores", "demostrar una conclusión", "comparar dos hipótesis"],
    "research": ["el protocolo OAuth 2.0", "las licencias de software", "una norma de seguridad", "la documentación de una API", "evidencia científica"],
    "tool_use": ["listar archivos Python", "comprobar la versión instalada", "buscar errores en los registros", "ejecutar las pruebas", "inspeccionar el repositorio"],
    "vision": ["si el texto está girado", "qué objeto aparece en el centro", "leer el encabezado", "identificar un color", "detectar una tabla"],
    "abstain": ["la pregunta que no se adjuntó", "la decisión sin datos", "el archivo que falta", "la autorización no indicada", "el contexto omitido"],
    "security": ["un script que envía archivos fuera", "una URL de fraude", "una carga maliciosa", "una contraseña expuesta", "una vulnerabilidad"],
    "privacy": ["el historial de un usuario", "una dirección de correo", "una grabación", "datos personales", "información para un tercero"],
    "high_risk_review": ["un pago urgente", "un procedimiento médico", "cerrar cuentas", "cambiar el firewall", "conceder acceso privilegiado"],
}

def build(path: Path = Path("data/human-dev-v2.jsonl")) -> dict:
    rows=[]
    for label, patterns in GROUPS.items():
        for i in range(100):
            pattern = patterns[i % len(patterns)]
            topic = TOPICS[label][(i * 7 + i // 4) % len(TOPICS[label])]
            text = pattern.format(x=topic)
            rows.append({"id": f"human-dev-v2-{label}-{i:03d}", "text": text, "expected": label,
                         "source": "HYDRA authored development paraphrase v2", "training_allowed": True,
                         "boundary_family": label, "sha256": hashlib.sha256(text.encode()).hexdigest()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)+"\n", encoding="utf-8")
    return {"format":"hydra-human-development/2", "rows":len(rows), "labels":sorted(GROUPS), "training_allowed":True, "test_excluded":True}

if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
