import json

import numpy as np
import pytest

from hyd_calibrator.contract import CRITERIA
from hyd_calibrator.e2_runtime import E2Runtime, write_manifest


def artifact(path, abstain=False):
    coef = np.arange(30, dtype=float).reshape(10, 3) / 10
    intercept = np.arange(10, dtype=float) / 100
    np.savez(path / "head.npz", coef=coef, intercept=intercept, labels=np.array(sorted(CRITERIA)),
             T=2.0, min_confidence=0.0, min_margin=0.0, abstain_all=abstain)
    (path / "report.json").write_text("{}", encoding="utf-8")
    write_manifest(path, "fixture-encoder", "a" * 40, {})
    return coef, intercept


def test_head_reload_matches_reference_and_remains_shadow(tmp_path):
    coef, intercept = artifact(tmp_path)
    embedding = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    scores = (embedding @ coef.T + intercept) / 2
    mass = np.exp(scores - scores.max(axis=1, keepdims=True))
    expected = mass / mass.sum(axis=1, keepdims=True)
    runtime = E2Runtime(tmp_path)
    actual = runtime.predict_embeddings(embedding)
    np.testing.assert_allclose([list(row["probabilities"].values()) for row in actual], expected)
    assert all(row["accepted"] and row["authority"] is False for row in actual)
    assert runtime.encoder is None


def test_explicit_abstain_all_survives_reload(tmp_path):
    artifact(tmp_path, abstain=True)
    assert E2Runtime(tmp_path).predict_embeddings([[1, 0, 0]])[0]["accepted"] is False


@pytest.mark.parametrize("name", ["head.npz", "report.json"])
def test_tampering_rejected_before_model_loading(tmp_path, name):
    artifact(tmp_path)
    with (tmp_path / name).open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        E2Runtime(tmp_path)


def test_authority_and_bad_embeddings_rejected(tmp_path):
    artifact(tmp_path)
    runtime = E2Runtime(tmp_path)
    for values in ([[1, 0]], [[2, 0, 0]], [[float("nan"), 0, 0]]):
        with pytest.raises(ValueError):
            runtime.predict_embeddings(values)
    manifest = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    manifest["authority"] = True
    (tmp_path / "runtime.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="contract"):
        E2Runtime(tmp_path)
