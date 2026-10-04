# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.verifier import Verifier


def test_empty_output_rejected():
    result = Verifier().verify_text("   ")
    assert result.accepted is False
    assert result.confidence == 0.0


def test_non_empty_output_structurally_accepted():
    result = Verifier().verify_text("A meaningful response.")
    assert result.accepted is True
    assert "non_empty_output" in result.evidence
