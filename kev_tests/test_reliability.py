# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Run with the Kev runtime and the patched source, not HYDRA's transformers."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
import copy
import torch
from kev.api import to_answers
from kev.checkpoint import Checkpoint, Meta
from kev.model import PointerHead
from kev.train import screen_custom_training


def test_serialization_preserves_small_probability_for_calibration():
    meta = [{"id": "task", "type": "choice", "keys": ["yes", "no"]}]
    p = [1-1e-8, 1e-8]
    answer = to_answers([p], meta)["task"]
    assert answer["probabilities"]["no"] == 1e-8
    assert answer["choice"] == "yes"


@pytest.mark.parametrize("probabilities", [[[.5]], [[float("nan"), .5]], [[0, 0]], [[-.1, 1.1]], []])
def test_malformed_model_outputs_are_rejected(probabilities):
    with pytest.raises(ValueError):
        to_answers(probabilities, [{"id": "task", "type": "choice", "keys": ["yes", "no"]}])


def test_preflight_rejects_wrong_base_without_loading_backbone():
    meta = Meta(base="Qwen/Qwen3.5-0.8B-Base", lora=16)
    fake_checkpoint = SimpleNamespace(meta=meta, path="candidate", COMPAT_FIELDS=Checkpoint.COMPAT_FIELDS)
    Checkpoint.validate_warm_start(fake_checkpoint, meta)
    with pytest.raises(ValueError, match="base is"):
        Checkpoint.validate_warm_start(fake_checkpoint, replace(meta, base="wrong-base"))


def test_temperature_readout_is_float32_and_many_matches_single():
    torch.manual_seed(42)
    head = PointerHead(8, 4).to(torch.bfloat16).eval()
    head.temperature = 3
    query = torch.randn(8).to(torch.bfloat16)
    options = torch.randn(3, 8).to(torch.bfloat16)
    single = head(query, options)
    many = head.many(query[None], options, torch.zeros(3, dtype=torch.long))
    assert single.dtype == torch.float32 and many.dtype == torch.float32
    assert torch.allclose(single, many, atol=.005, rtol=.01)


def test_training_screen_deduplicates_and_rejects_conflicting_labels():
    record = {"state": "A task", "questions": {"task": {"type": "choice", "criteria": {"a": "A", "b": "B"}, "label": "a"}}}
    assert screen_custom_training([record, copy.deepcopy(record)]) == [record]
    other = copy.deepcopy(record)
    other["questions"]["task"]["label"] = "b"
    with pytest.raises(ValueError, match="conflicting"):
        screen_custom_training([record, other])


@pytest.mark.parametrize("flag", [{"training_allowed": False}, {"_meta": {"split": "test"}}, {"_meta": {"split": "calibration"}}])
def test_held_out_training_is_rejected(flag):
    with pytest.raises(ValueError, match="held-out"):
        screen_custom_training([{"state": "x", "questions": {}, **flag}])
