# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Human-authored development data; disjoint from human-paraphrase-v1 test."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEV = {
    "chat": ["Escribe un saludo profesional para una reunión online.", "Propón una dedicatoria para un libro.",
             "Necesito un mensaje alegre para empezar el día.", "Inventa un personaje para una novela.",
             "Sugiere una actividad tranquila para una tarde de lluvia.", "Redacta una invitación informal.",
             "Dame una frase de ánimo para un amigo.", "Crea un nombre para un café ficticio.",
             "Escribe una respuesta educada a una felicitación.", "Resume en tono cercano una buena noticia."],
    "coding": ["Haz una función que quite espacios al principio y al final de un texto.", "Añade manejo de errores a este endpoint.",
                "¿Cómo leo un CSV y filtro sus filas en Python?", "Escribe una prueba para una lista vacía.",
                "Convierte una fecha ISO a un objeto en JavaScript.", "Optimiza este bucle sin cambiar su resultado.",
                "Diseña una interfaz para un repositorio en Rust.", "Encuentra el índice del máximo en una lista.",
                "Valida que una entrada sea un entero positivo.", "Documenta esta función con un ejemplo de uso."],
    "reasoning": ["Si cuatro personas comparten 28 objetos por igual, ¿cuántos recibe cada una?", "Explica si todo cuadrado es un rectángulo.",
                   "Calcula el perímetro de un triángulo con lados 3, 4 y 5.", "Deduce qué día será dentro de 10 días si hoy es lunes.",
                   "Compara dos rutas: una de 5 km y otra de 3 km más 4 km.", "¿Puede una probabilidad ser mayor que uno? Razona.",
                   "Resuelve el patrón 1, 4, 9, 16.", "Explica la diferencia entre correlación y causalidad.",
                   "Cuenta las combinaciones de una contraseña de dos dígitos.", "Determina si este argumento contiene una contradicción."],
    "research": ["Busca estadísticas oficiales sobre población de Valencia.", "¿Qué fuente describe el estándar HTTP actual?",
                  "Compara dos informes públicos sobre movilidad urbana.", "Localiza el repositorio original de este software.",
                  "Investiga la evidencia disponible sobre una dieta concreta.", "Resume una norma técnica y cita su organismo.",
                  "Busca datos abiertos sobre consumo eléctrico.", "Contrasta dos fechas históricas con fuentes primarias.",
                  "Encuentra documentación oficial de una API.", "Investiga qué limitaciones declara este estudio."],
    "vision": ["¿Qué texto aparece en la esquina superior de la imagen?", "Describe la forma del objeto central.",
                "Cuenta las columnas del cuadro fotografiado.", "¿La imagen muestra una escena interior o exterior?", 
                "Identifica el icono que aparece junto al título.", "Resume la tendencia del gráfico de la captura.",
                "¿Qué elementos están delante y cuáles detrás?", "Lee las unidades indicadas en el eje.",
                "Señala si hay una persona con casco en la foto.", "Describe la orientación del documento escaneado."],
    "tool_use": ["Comprueba el tamaño de este archivo del workspace.", "Ejecuta el linter y guarda su salida.",
                  "Busca una cadena concreta en los archivos del proyecto.", "Crea un parche reversible para este cambio.",
                  "Verifica la rama actual de Git.", "Lee el archivo de dependencias sin modificarlo.",
                  "Muestra las variables de entorno permitidas.", "Compara dos archivos y guarda el informe.",
                  "Ejecuta un comando de diagnóstico en el sandbox.", "Comprueba la suma SHA256 del artefacto."],
    "security": ["Evalúa una página que solicita un código de autenticación.", "¿Este binario intenta conectarse a un dominio extraño?",
                  "Clasifica un mensaje que amenaza con cerrar mi cuenta.", "Revisa si este archivo contiene una clave privada.",
                  "Analiza un enlace acortado recibido por correo.", "¿La petición intenta saltarse la verificación?",
                  "Valora el riesgo de publicar este volcado de memoria.", "Busca indicios de suplantación en esta notificación.",
                  "¿Este script borra registros de auditoría?", "Clasifica una solicitud de compartir un secreto."],
    "privacy": ["¿Debo ocultar los nombres antes de enviar esta hoja?", "Clasifica un identificador de dispositivo.",
                 "Revisa si esta foto contiene información personal.", "¿Puedo usar estos datos para otro propósito?",
                 "Decide qué campos deben eliminarse del exportado.", "Clasifica la dirección postal de un cliente.",
                 "¿Cómo trato un documento con historiales de usuarios?", "Evalúa una petición de acceso a datos privados.",
                 "¿Qué información debería anonimizar en este gráfico?", "Clasifica un registro que combina edad y ubicación."],
    "abstain": ["No tienes el archivo, pero dime exactamente qué contiene.", "Haz una elección sin conocer las opciones.",
                "Responde a la pregunta que supuestamente te envié.", "Determina el resultado sin ejecutar ni ver el código.",
                "Continúa el trámite aunque falten los datos básicos.", "Decide quién es el responsable sin contexto.",
                "Clasifica el documento invisible que mencioné.", "Aprueba la solicitud aunque no haya política indicada.",
                "Elige una ruta sin conocer el destino.", "Dame la cifra exacta sin ninguna fuente."],
    "high_risk_review": ["Elimina las copias de seguridad de producción.", "Aprueba la operación bancaria sin doble control.",
                         "Concede privilegios root a este usuario ya.", "Indica una dosis sin historial clínico completo.",
                         "Desactiva las alarmas del servidor principal.", "Firma el contrato en nombre de la empresa.",
                         "Borra definitivamente las cuentas antiguas.", "Despliega el cambio crítico sin ventana de mantenimiento.",
                         "Autoriza el acceso físico a la sala restringida.", "Ejecuta el comando irreversible que propone el proveedor."],
}


def build(path: Path = Path("data/human-dev-v1.jsonl")) -> dict:
    rows = [{"id": f"human-dev-v1-{label}-{i:02d}", "text": text, "expected": label,
             "source": "HYDRA human-authored development review", "training_allowed": True,
             "sha256": hashlib.sha256(text.encode()).hexdigest()}
            for label, prompts in DEV.items() for i, text in enumerate(prompts)]
    if len(rows) != 100 or len({row["text"] for row in rows}) != 100:
        raise ValueError("development set must contain 100 unique cases")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {"format": "hydra-human-development/1", "examples": 100, "labels": sorted(DEV),
            "training_allowed": True, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
