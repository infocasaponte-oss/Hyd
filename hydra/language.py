# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Lightweight local language detection (no model): routing signal for ``language.translate``
and corpus language tags. A trained HYDRA classifier can replace it behind the same API."""

from __future__ import annotations

import re

from pydantic import BaseModel

LANGUAGE_HINTS: dict[str, dict] = {
    "es": {"words": {"que", "para", "como", "con", "una", "por", "gracias", "hola", "buenos", "el", "los", "las",
                     "del", "es", "está", "qué", "cómo", "cuánto", "y", "pero", "este", "esta", "muy", "también"},
           "chars": "ñ¿¡áéíóú"},
    "en": {"words": {"the", "and", "with", "for", "hello", "thanks", "what", "how", "this", "is", "are", "of",
                     "to", "you", "that", "it", "please", "which", "does", "from"}, "chars": ""},
    "fr": {"words": {"le", "la", "les", "avec", "pour", "bonjour", "merci", "comment", "est", "une", "des", "et",
                     "je", "vous", "que", "qui", "pas", "sur", "dans", "très"}, "chars": "àâçèêëîïôùûüÿœ"},
    "de": {"words": {"der", "die", "das", "und", "mit", "für", "hallo", "danke", "wie", "ist", "nicht", "ein",
                     "eine", "ich", "sie", "zu", "auf", "auch", "bitte", "wir"}, "chars": "äöüß"},
    "pt": {"words": {"os", "as", "com", "para", "olá", "obrigado", "obrigada", "como", "não", "uma", "você", "é",
                     "do", "da", "em", "que", "muito", "também", "isso", "está"}, "chars": "ãõç"},
    "it": {"words": {"il", "gli", "con", "per", "ciao", "grazie", "come", "non", "una", "sono", "che", "di",
                     "della", "questo", "anche", "molto", "perché", "è", "le", "lo"}, "chars": "ìò"},
    "gl": {"words": {"moi", "grazas", "non", "unha", "cando", "tamén", "onde", "vostede", "ola", "coma", "polo",
                     "pola", "dos", "das", "xa", "agora", "ese", "esa"}, "chars": "ñ"},
    "ca": {"words": {"amb", "per", "que", "una", "és", "gràcies", "hola", "com", "molt", "també", "aquest", "els",
                     "les", "del", "però"}, "chars": "àèòç·"},
}
LANGUAGE_NAMES = {"es": "Spanish", "en": "English", "fr": "French", "de": "German", "pt": "Portuguese",
                  "it": "Italian", "gl": "Galician", "ca": "Catalan", "zh": "Chinese", "ja": "Japanese",
                  "ko": "Korean", "ru": "Russian", "ar": "Arabic", "el": "Greek"}
SCRIPTS = [("zh", re.compile(r"[一-鿿]")), ("ja", re.compile(r"[぀-ヿ]")),
           ("ko", re.compile(r"[가-힯]")), ("ru", re.compile(r"[Ѐ-ӿ]")),
           ("ar", re.compile(r"[؀-ۿ]")), ("el", re.compile(r"[Ͱ-Ͽ]"))]
WORD = re.compile(r"[a-zA-ZÀ-ÿ]+")
TRANSLATE_HINT = re.compile(r"(?i)\b(?:traduce|traducir|tradúceme|translate|traduire|übersetze|traduza|tradurre|"
                            r"traducción|translation)\b(?:.{0,60}?\b(?:al|a|to|en|into|in|ao|in)\s+"
                            r"(?P<lang>[a-záéíóúñ]+))?")
TARGET_ALIASES = {"inglés": "en", "ingles": "en", "english": "en", "español": "es", "castellano": "es",
                  "spanish": "es", "francés": "fr", "frances": "fr", "french": "fr", "alemán": "de", "aleman": "de",
                  "german": "de", "portugués": "pt", "portugues": "pt", "portuguese": "pt", "italiano": "it",
                  "italian": "it", "gallego": "gl", "galego": "gl", "galician": "gl", "catalán": "ca", "catalan": "ca",
                  "chino": "zh", "chinese": "zh", "japonés": "ja", "japanese": "ja", "ruso": "ru", "russian": "ru"}


def detect_scores(text: str) -> dict[str, float]:
    clean = text.lower()
    for code, rx in SCRIPTS:
        if len(rx.findall(text)) >= 2:
            return {code: 10.0}
    tokens = WORD.findall(clean)
    counts: dict[str, float] = {}
    for lang, hints in LANGUAGE_HINTS.items():
        score = sum(1.0 for t in tokens if t in hints["words"])
        score += sum(0.75 for ch in hints["chars"] if ch in clean)
        counts[lang] = score
    return counts


def detect_language(text: str) -> str:
    scores = detect_scores(text)
    best = max(scores, key=scores.get) if scores else "unknown"
    return best if scores.get(best, 0) > 0 else "unknown"


def language_confidence(text: str) -> tuple[str, float]:
    scores = detect_scores(text)
    if not scores:
        return "unknown", 0.0
    ranked = sorted(scores.values(), reverse=True)
    best = max(scores, key=scores.get)
    if ranked[0] <= 0:
        return "unknown", 0.0
    margin = (ranked[0] - (ranked[1] if len(ranked) > 1 else 0)) / ranked[0]
    return best, round(min(0.99, 0.5 + 0.5 * margin), 3)


def normalize_language(name: str | None) -> str | None:
    if not name:
        return None
    n = name.strip().lower()
    if n in LANGUAGE_NAMES:
        return n
    if n in TARGET_ALIASES:
        return TARGET_ALIASES[n]
    for code, full in LANGUAGE_NAMES.items():
        if full.lower() == n:
            return code
    return n[:2]


class LanguageRoute(BaseModel):
    source_language: str
    target_language: str | None = None
    capability: str
    confidence: float


def route_language(text: str, target_language: str | None = None) -> LanguageRoute:
    """``chat.multilingual`` vs ``language.translate`` (explicit target or a translate instruction)."""
    source, conf = language_confidence(text)
    if not target_language and (m := TRANSLATE_HINT.search(text)):
        target_language = normalize_language(m.group("lang")) if m.group("lang") else None
        if target_language is None:
            target_language = "en" if source != "en" else "es"
    if target_language:
        return LanguageRoute(source_language=source, target_language=normalize_language(target_language),
                             capability="language.translate", confidence=max(0.55, conf))
    return LanguageRoute(source_language=source, capability="chat.multilingual", confidence=max(0.5, conf))
