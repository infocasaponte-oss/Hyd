# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.model_factory.finish import preload
from hydra.training.verified_corpus import sha256


def test_preloaded_tests_are_pinned_and_require_references(tmp_path):
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps([{'id': 1, 'prompt': 'Hello', 'expected_response': 'Hi'}]))
    config = {'suites': [{'path': str(path), 'sha256': sha256(path)}]}
    pins, suites = preload(config)
    assert pins[str(path)] == sha256(path)
    assert len(suites[0][1]) == 1
    path.write_text('[]')
    with pytest.raises(ValueError, match='changed'):
        preload(config)


def test_duplicate_questions_cannot_silently_count_twice(tmp_path):
    path = tmp_path / 'cases.json'
    row = {'id': 1, 'prompt': 'Hello', 'expected_response': 'Hi'}
    path.write_text(json.dumps([row, row]))
    with pytest.raises(ValueError, match='Duplicate'):
        preload({'suites': [{'path': str(path), 'sha256': sha256(path)}]})
