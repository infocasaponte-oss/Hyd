# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4a): the structural verifier is ``hydra.verification.verifier.Verifier.verify_text``."""
from __future__ import annotations

from hydra.verification.verifier import TextVerification as VerificationResult
from hydra.verification.verifier import Verifier

__all__ = ["VerificationResult", "Verifier"]
