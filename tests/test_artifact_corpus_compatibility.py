# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib
import json
from pathlib import Path

import pytest

from hydra.corpus.artifact_candidates import CorpusGate, CorpusRecord, RightsDeclaration
from hydra.corpus.privacy_contracts import PrivacyScanResult

CASES = json.loads((Path(__file__).parent / "fixtures/artifact_admission_baseline.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES)
def test_admission_and_hash_match_frozen_original_implementation(case):
    confirmed, reviewed, allowed, evidence = case["flags"]
    record = CorpusRecord(
        task_id="00000000-0000-0000-0000-000000000001",
        belief_id="00000000-0000-0000-0000-000000000002",
        artifact_hashes=["a" * 64],
        rights=RightsDeclaration(rights_confirmed=confirmed, privacy_reviewed=reviewed,
                                 training_allowed=allowed, source_license="internal" if evidence else None),
        privacy_scan=PrivacyScanResult(status=case["privacy_status"]),
    )
    result = CorpusGate().evaluate(record)
    assert result.status.value == case["status"]
    assert result.content_hash == case["content_hash"]


@pytest.mark.parametrize("old,new", [
    ("hydra.runtime.corpus", "hydra.corpus.artifact_candidates"),
    ("hydra.runtime.outbox_dispatcher", "hydra.core.outbox_dispatcher"),
])
def test_legacy_module_is_canonical(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def test_privacy_contracts_keep_class_identity():
    from hydra.runtime.privacy import PrivacyScanResult as LegacyResult
    assert LegacyResult is PrivacyScanResult
