# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Source-coverage guard: no answer about something the supplied source does not contain.

When a request supplies source material (legal articles with "Artículo N." headings, or code
defining functions/classes) and the question asks about an article or a code name that the
source does not contain, the only grounded answer is to say so. Any other answer describes
content the model cannot have read and is rejected; ``repair`` gives the deterministic
abstention. Requests without source material are left alone (general knowledge stays allowed).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from hydra.core.contracts import HydraRequest

ARTICLE_HEADER = re.compile(r"^\s*Art[íi]culo\s+(\d+(?:\s+(?:bis|ter|quater))?)\s*\.", re.I | re.M)
_NUM = r"\d+(?:\s+(?:bis|ter|quater))?"
# "artículo 17", "art. 4", "artículos 17 y 20", "arts. 3, 4 y 5"
ARTICLE_REF = re.compile(rf"\bart(?:[íi]culos?|s?\.)\s*({_NUM}(?:\s*(?:,|\by\b|\be\b)\s*{_NUM})*)", re.I)
ARTICLE_NUM = re.compile(_NUM, re.I)
CODE_DEF = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)", re.M)
# Only `backticked` identifiers: prose such as "una función en Python" must not name code.
CODE_REF = re.compile(r"`([A-Za-z_]\w*)`")
ABSTAIN = re.compile(
    r"\bno (?:contiene|incluye|aparece|figura|define|recoge|está|se (?:encuentra|menciona|incluye|define|recoge))\b|"
    r"\bsolo (?:incluye|contiene|recoge)\b|\bno (?:puedo|es posible) (?:indicar|responder|determinar|saber|decir)\b|"
    r"\b(?:does not|doesn't) (?:contain|include|define)\b|\bnot (?:included|defined|present) in\b", re.I)


@dataclass(frozen=True)
class Coverage:
    missing_articles: tuple[str, ...]
    missing_names: tuple[str, ...]

    @property
    def missing(self) -> bool:
        return bool(self.missing_articles or self.missing_names)


def has_source(text: str) -> bool:
    """True when the text supplies source material: legal "Artículo N." headings or code definitions."""
    return bool(ARTICLE_HEADER.search(text) or CODE_DEF.search(text))


URL = re.compile(r"https?://[^\s<>()«»\"']+")
_CITED_URL = r"[ \t]*(?:\(?(?:Fuente|Source|Ver|Véase)[ \t]*:[ \t]*)?{url}\)?\.?"


def strip_unsourced_urls(answer: str, source: str) -> tuple[str, list[str]]:
    """Remove URLs (and their "Fuente:" label) that the supplied source does not contain: a model
    trained on cited sources invents a plausible link when the source has none. Only the removed
    spans change; indentation and code elsewhere in the answer are left as they are."""
    known = {u.rstrip(".,;:") for u in URL.findall(source)}
    invented = [u for u in dict.fromkeys(URL.findall(answer)) if u.rstrip(".,;:") not in known]
    if not invented:
        return answer, []
    for url in invented:
        # Markdown link: keep its text, drop only the target.
        answer = re.sub(rf"\[([^\]]*)\]\({re.escape(url)}\)", r"\1", answer)
        answer = re.sub(_CITED_URL.format(url=re.escape(url)), "", answer)
    return answer.strip(), invented


def _norm(number: str) -> str:
    return re.sub(r"\s+", " ", number.strip().lower())


def coverage(request: HydraRequest) -> Coverage | None:
    """Units the question asks about that the supplied source lacks; None without source material."""
    source = request.text
    question = request.last_user_text
    provided_articles = {_norm(n) for n in ARTICLE_HEADER.findall(source)}
    defined = set(CODE_DEF.findall(source))
    if not provided_articles and not defined:
        return None
    asked_text = _question_part(question)
    missing_articles: tuple[str, ...] = ()
    if provided_articles:
        asked = [_norm(n) for group in ARTICLE_REF.findall(asked_text) for n in ARTICLE_NUM.findall(group)]
        missing_articles = tuple(dict.fromkeys(n for n in asked if n not in provided_articles))
    missing_names: tuple[str, ...] = ()
    if defined:
        code = _code_text(request)
        asked = CODE_REF.findall(_prose(asked_text))
        # A name used anywhere in the code (called, imported, assigned) is not "absent".
        missing_names = tuple(dict.fromkeys(n for n in asked if n not in defined
                                            and not re.search(rf"\b{re.escape(n)}\b", code)))
    return Coverage(missing_articles, missing_names)


FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def _question_part(question: str) -> str:
    """The question itself. When the source is pasted in the same message, its body often cites
    other articles ("lo dispuesto en el artículo 142"), so only the last paragraph counts."""
    if not (ARTICLE_HEADER.search(question) or CODE_DEF.search(question) or "```" in question):
        return question
    paragraphs = [p for p in re.split(r"\n\s*\n", FENCE.sub("", question)) if p.strip()]
    return paragraphs[-1] if paragraphs else ""


def _code_text(request: HydraRequest) -> str:
    """Code of the source: fenced blocks anywhere plus earlier (non-question) messages."""
    earlier = [m.content for m in request.messages if m.content != request.last_user_text]
    return "\n".join(FENCE.findall(request.text) + earlier)


def _prose(text: str) -> str:
    return FENCE.sub("", text)


def abstains(answer: str) -> bool:
    return ABSTAIN.search(answer) is not None


def repair(cov: Coverage) -> str:
    """Deterministic abstention naming exactly what the source lacks."""
    parts = []
    if cov.missing_articles:
        arts = cov.missing_articles
        label = f"el artículo {arts[0]}" if len(arts) == 1 else \
            "los artículos " + ", ".join(arts[:-1]) + f" y {arts[-1]}"
        parts.append(f"La fuente proporcionada no incluye {label}, así que no puedo indicar qué establece "
                     "a partir de ella.")
    if cov.missing_names:
        names = ", ".join(f"`{n}`" for n in cov.missing_names)
        parts.append(f"El código proporcionado no define {names}, así que no puedo responder sobre ello "
                     "con esta fuente.")
    return " ".join(parts)
