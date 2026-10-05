# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Explicit source declarations; validation never manufactures ownership."""


def require_consent_and_rights(row):
    if not isinstance(row, dict) or row.get("consent") is not True:
        raise ValueError("explicit consent=true required")
    rights = row.get("rights")
    if (
        not isinstance(rights, dict)
        or rights.get("verified") is not True
        or not isinstance(rights.get("license"), str)
        or not rights["license"].strip()
    ):
        raise ValueError("declared source rights required")
    return rights


CONTRIBUTED_LICENSE = "contributed-with-consent"


def require_contributed_consent(row):
    """Questions contributed by other people with explicit in-app consent.

    They are NOT HYDRA-authored and must never be relabelled as such. Rights are
    declared by the contributor's consent, not third-party verified, so
    ``rights.verified`` is not required; a claim of HYDRA authorship is rejected.
    """
    if not isinstance(row, dict) or row.get("consent") is not True:
        raise ValueError("explicit consent=true required")
    rights = row.get("rights")
    if not isinstance(rights, dict) or rights.get("license") != CONTRIBUTED_LICENSE:
        raise ValueError("contributed rows require rights.license=contributed-with-consent")
    if not isinstance(rights.get("declared_by"), str) or not rights["declared_by"].strip():
        raise ValueError("contributed rows require rights.declared_by")
    if rights.get("hydra_authored") is True:
        raise ValueError("contributed rows cannot claim HYDRA authorship")
    person = (row.get("meta") or {}).get("person")
    if not isinstance(person, str) or not person.strip():
        raise ValueError("contributed rows require meta.person")
    return rights
