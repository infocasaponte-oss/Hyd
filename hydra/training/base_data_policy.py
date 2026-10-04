# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Data and teacher licence policy for HYDRA Base (weights trained from scratch, proprietary licence).

HYDRA uses a conservative project allowlist: share-alike, copyleft, non-commercial,
no-derivatives and unknown declarations are excluded. This does not determine whether a
particular licence legally applies to model weights. A permitted label is only a compatibility
check: lawful access, attribution, third-party rights, privacy and applicable TDM reservations
still need evidence and review. ``attribution_notice`` collects declared release notices.
An unlisted licence is rejected. This is an engineering control, not a legal clearance.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# licence id -> obligation that survives into a proprietary release
PERMITTED: dict[str, str] = {
    "public-domain": "",
    "CC0-1.0": "",
    "Unlicense": "",
    "0BSD": "",
    "hydra-generated": "",
    "CC-BY-4.0": "Atribución al autor y a la fuente (CC BY 4.0).",
    "MIT": "Conservar el aviso de copyright y de permiso MIT.",
    "BSD-2-Clause": "Conservar el aviso de copyright BSD-2-Clause.",
    "BSD-3-Clause": "Conservar el aviso BSD-3-Clause; no usar los nombres de los autores para promocionar.",
    "ISC": "Conservar el aviso de copyright ISC.",
    "Apache-2.0": "Conservar los avisos de licencia y NOTICE de Apache-2.0.",
    # Ley 37/2007 y RD 1495/2011: reutilización con cita de la fuente, sin desnaturalizar el dato.
    "es-public-sector-reuse": "Citar la fuente (p. ej. «Fuente: Agencia Estatal BOE») y la fecha de actualización.",
    # Decision 2011/833/EU concerns Commission documents; verify scope/third-party rights per source.
    "eu-reuse-2011-833": "Citar «© Unión Europea, https://eur-lex.europa.eu» e indicar si se ha modificado.",
}

# Declarations excluded by the conservative project policy; not conclusions about all model weights.
FORBIDDEN = [
    (re.compile(r"(^|-)SA(-|$)|share.?alike", re.I), "share-alike: fuera de la política conservadora del proyecto"),
    (re.compile(r"^(A|L)?GPL|copyleft|^MPL|^EPL|^CDDL", re.I), "copyleft: impone condiciones a obras derivadas"),
    (re.compile(r"(^|-)NC(-|$)|non.?commercial", re.I), "no comercial"),
    (re.compile(r"(^|-)ND(-|$)|no.?deriv", re.I), "prohíbe obras derivadas"),
]

# Teacher models whose outputs may be distilled into HYDRA Base.
PERMITTED_TEACHER_LICENSES = {"Apache-2.0", "MIT"}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    license: str
    reason: str
    obligation: str = ""


def admit_source(license_id: str | None) -> Decision:
    """Whether material under ``license_id`` may enter HYDRA Base pretraining."""
    lic = (license_id or "").strip()
    if not lic:
        return Decision(False, "", "licencia desconocida: se rechaza por defecto")
    for pattern, why in FORBIDDEN:
        if pattern.search(lic):
            return Decision(False, lic, why)
    if lic in PERMITTED:
        return Decision(True, lic, "compatible con pesos propietarios", PERMITTED[lic])
    return Decision(False, lic, "licencia no incluida en la lista permitida: revisión manual necesaria")


def admit_record(licenses: Iterable[str] | str | None) -> Decision:
    """A record may carry several licences (dual licensing excluded): every one must be admitted."""
    items = [licenses] if isinstance(licenses, str) or licenses is None else list(licenses)
    if not items:
        return admit_source(None)
    decisions = [admit_source(item) for item in items]
    rejected = next((d for d in decisions if not d.allowed), None)
    if rejected:
        return rejected
    return Decision(True, ", ".join(d.license for d in decisions), "compatible con pesos propietarios",
                    " ".join(dict.fromkeys(d.obligation for d in decisions if d.obligation)))


def admit_teacher(model_license: str | None) -> Decision:
    lic = (model_license or "").strip()
    if lic in PERMITTED_TEACHER_LICENSES:
        return Decision(True, lic, "profesor con licencia permisiva: sus salidas pueden destilarse")
    return Decision(False, lic, "profesor no permitido: su licencia restringe el uso de salidas o derivados")


def attribution_notice(sources: Iterable[dict]) -> str:
    """Third-party data notice for a HYDRA Base release, grouped by licence.

    ``sources``: dicts with ``name``, ``license`` and optional ``url`` / ``attribution``.
    Raises if any source would not be admitted, so a release cannot ship with one.
    """
    groups: dict[str, list[str]] = {}
    for source in sources:
        decision = admit_source(source.get("license"))
        if not decision.allowed:
            raise ValueError(f"{source.get('name')}: {decision.reason}")
        if not decision.obligation:
            continue
        line = f"- {source['name']}" + (f" ({source['url']})" if source.get("url") else "")
        if source.get("attribution"):
            line += f": {source['attribution']}"
        groups.setdefault(decision.license, []).append(line)
    parts = ["HYDRA Base: avisos de datos de terceros", ""]
    for lic in sorted(groups):
        parts += [f"{lic} — {PERMITTED[lic]}", *sorted(set(groups[lic])), ""]
    return "\n".join(parts).rstrip() + "\n"
