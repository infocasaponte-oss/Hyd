# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYD-024 · contributed-with-consent rows: admitted only when explicitly allowed, never as HYDRA-authored."""
import json

import pytest

from hyd_calibrator.admission import require_contributed_consent
from hydra.hyd.train import rows


def contributed(**over):
    row = {"consent": True, "rights": {"license": "contributed-with-consent", "declared_by": "contributor-consent-in-app"},
           "split": "train", "training_allowed": True, "input": {"query": "¿Que tempo fai mañá en Vigo?"},
           "output": {"task_type": "chat"}, "meta": {"person": "person-juan"}}
    row.update(over)
    return row


def write(tmp_path, row):
    p = tmp_path / "rows.jsonl"; p.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"); return p


def test_default_still_rejects_contributed(tmp_path):
    with pytest.raises(ValueError):
        rows(write(tmp_path, contributed()), training=True)


def test_allowed_contributed_is_admitted_and_text_kept_exact(tmp_path):
    r = rows(write(tmp_path, contributed()), training=True, allow_contributed=True)
    assert r == [{"text": "¿Que tempo fai mañá en Vigo?", "label": "chat", "license": "contributed-with-consent"}]


@pytest.mark.parametrize("consent", [False, None, "true", 1])
def test_contributed_requires_literal_consent(tmp_path, consent):
    with pytest.raises(ValueError, match="consent"):
        rows(write(tmp_path, contributed(consent=consent)), training=True, allow_contributed=True)


def test_contributed_cannot_claim_hydra_authorship():
    row = contributed(); row["rights"]["hydra_authored"] = True
    with pytest.raises(ValueError, match="HYDRA"):
        require_contributed_consent(row)


def test_contributed_requires_person_and_declarer():
    with pytest.raises(ValueError, match="person"):
        require_contributed_consent(contributed(meta={}))
    row = contributed(); row["rights"]["declared_by"] = " "
    with pytest.raises(ValueError, match="declared_by"):
        require_contributed_consent(row)


def test_owner_rows_unchanged_with_flag(tmp_path):
    owner = {"consent": True, "rights": {"verified": True, "license": "proprietary-hydra-authored"}, "split": "train",
             "training_allowed": True, "input": {"query": "Cal é a capital de Níxer?"}, "output": {"task_type": "chat"}}
    assert rows(write(tmp_path, owner), training=True, allow_contributed=True)[0]["license"] == "proprietary-hydra-authored"
    owner["rights"]["verified"] = False
    with pytest.raises(ValueError, match="rights"):
        rows(write(tmp_path, owner), training=True, allow_contributed=True)
