# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Require a scoped human declaration and hashed evidence for a book asset."""
from .corpus_readiness import valid_evidence

BOOK_HOSTS = {"elejandria": {"www.elejandria.com", "elejandria.com"},
              "textos-info": {"www.textos.info", "textos.info"},
              "cervantes": {"www.cervantesvirtual.com", "cervantesvirtual.com"},
              "gutenberg": {"www.gutenberg.org", "gutenberg.org"}}


def validate_work(review, source_id, asset_url, license_name):
    if not isinstance(review, dict) or review.get("format") != "hyd-book-work-review/1":
        raise ValueError("per-work review required")
    reviewer = review.get("reviewer")
    if (review.get("review_status") != "reviewed" or not isinstance(reviewer, dict)
            or reviewer.get("kind") != "human" or not isinstance(reviewer.get("id"), str) or not reviewer["id"].strip()):
        raise ValueError("documented human work review required")
    if (review.get("source_id") != source_id or review.get("asset_url") != asset_url
            or review.get("license") != license_name or review.get("training_allowed") is not False):
        raise ValueError("work review must bind exact source, asset and license")
    if (not isinstance(review.get("work_id"), str) or not review["work_id"].strip()
            or not isinstance(review.get("edition_id"), str) or not review["edition_id"].strip()
            or not isinstance(review.get("territories"), list) or "ES" not in review["territories"]):
        raise ValueError("work, edition and Spanish territorial review required")
    for field in ("work_rights", "translation_rights", "edition_rights", "source_access", "tdm_reservations", "attribution"):
        if review.get(field) not in ("reviewed", "not-applicable-reviewed"):
            raise ValueError(f"book {field} pending")
    if not isinstance(review.get("evidence"), list) or not review["evidence"]:
        raise ValueError("work evidence required")


def verify_work_files(review, root):
    if not valid_evidence(review["evidence"], root.resolve(strict=True)):
        raise ValueError("book evidence files missing, unsafe or hash mismatch")
