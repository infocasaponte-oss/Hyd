# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Answer narrow engine-ownership questions from configured project metadata."""
import re


def creator_answer(text: str, creator: str) -> str | None:
    if not creator:
        return None
    clean = text.strip().lower().strip("¿?!. ")
    if re.fullmatch(r"(?:quen|quién|quien) (?:te creou|te creó|te creo|creou hydra|creó hydra)", clean):
        if clean.startswith("quen"):
            return f"O motor HYDRA foi creado por {creator}."
        return f"El motor HYDRA fue creado por {creator}."
    return None
