# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F4a: characterisation of the runtime line's structural verifier (written against
``hydra.runtime.verifier`` before it was absorbed by ``hydra.verification.verifier``). Both import paths
must keep giving exactly these results."""
from __future__ import annotations

import pytest

from hydra.runtime.verifier import VerificationResult as RuntimeResult
from hydra.runtime.verifier import Verifier as RuntimeVerifier
from hydra.verification.verifier import TextVerification, Verifier


@pytest.mark.parametrize("cls", [RuntimeVerifier, Verifier])
@pytest.mark.parametrize("answer, accepted, confidence, reason, evidence", [
    ("", False, 0.0, "empty_answer", []),
    ("   \n\t ", False, 0.0, "empty_answer", []),
    ("ok", True, 0.45, "structural_checks_passed", ["non_empty_output"]),
    ("  1234567  ", True, 0.45, "structural_checks_passed", ["non_empty_output"]),  # 7 chars once stripped
    ("12345678", True, 0.60, "structural_checks_passed", ["non_empty_output"]),
    ("A meaningful response.", True, 0.60, "structural_checks_passed", ["non_empty_output"]),
    ("Lo siento, no puedo ayudar con eso.", True, 0.60, "structural_checks_passed", ["non_empty_output"]),
])
def test_structural_verification(cls, answer, accepted, confidence, reason, evidence):
    result = cls().verify_text(answer)
    assert (result.accepted, result.confidence, result.reason, result.evidence) == \
        (accepted, confidence, reason, evidence)


def test_one_result_type_for_both_import_paths():
    assert RuntimeResult is TextVerification and RuntimeVerifier is Verifier
    assert set(TextVerification.model_fields) == {"accepted", "confidence", "evidence", "reason"}
