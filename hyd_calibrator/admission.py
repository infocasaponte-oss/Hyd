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
