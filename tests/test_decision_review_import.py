# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json

import pytest

from hydra.training.decision_review_import import import_reviews, rescore_rows


@pytest.fixture
def review_files(tmp_path):
    corpus = tmp_path / 'corpus.jsonl'
    row = {'id': 'fixture', 'text': 'Pregunta sintética', 'person': 'fixture-person',
           'family': 'fixture-family', 'expected': 'abstain'}
    row['text_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
    corpus.write_text(json.dumps(row), encoding='utf-8')
    event = {**row, 'source_sha256': hashlib.sha256(corpus.read_bytes()).hexdigest(),
             'human_label': 'privacy', 'reviewer': 'Synthetic reviewer', 'confirmed': True,
             'training_allowed': False, 'reviewed_at': '2026-10-05T18:00:00+00:00', 'notes': 'Confirmado'}
    events = tmp_path / 'events.jsonl'
    events.write_text(json.dumps(event), encoding='utf-8')
    return corpus, events, row, event


def test_import_versions_label_and_preserves_original(review_files, tmp_path):
    corpus, events, original, event = review_files
    before = corpus.read_bytes()
    result = import_reviews(corpus, events, tmp_path / 'new')
    corrected = json.loads((tmp_path / 'new/corpus_reviewed.jsonl').read_text(encoding='utf-8'))
    assert result['changed_rows'] == 1 and corpus.read_bytes() == before
    assert corrected['expected'] == 'privacy' and corrected['label_review']['previous_expected'] == 'abstain'
    assert all(corrected[k] == original[k] for k in ('id', 'text', 'text_sha256', 'person', 'family'))


@pytest.mark.parametrize('key,value', [('text', 'Alterado'), ('confirmed', False), ('source_sha256', 'wrong'), ('reviewer', '')])
def test_import_rejects_invalid_review(review_files, tmp_path, key, value):
    corpus, events, _, event = review_files
    events.write_text(json.dumps({**event, key: value}), encoding='utf-8')
    with pytest.raises(ValueError):
        import_reviews(corpus, events, tmp_path / 'new')
    assert not (tmp_path / 'new').exists()


def test_latest_timestamp_wins_and_ambiguity_is_not_relabelled(review_files, tmp_path):
    corpus, events, _, event = review_files
    later = {**event, 'human_label': 'ambiguous', 'reviewed_at': '2026-10-05T19:00:00+00:00'}
    events.write_text(json.dumps(later) + '\n' + json.dumps(event), encoding='utf-8')
    result = import_reviews(corpus, events, tmp_path / 'new')
    assert result['unresolved_rows'] == 1 and result['changed_rows'] == 0
    assert json.loads((tmp_path / 'new/corpus_reviewed.jsonl').read_text(encoding='utf-8'))['expected'] == 'abstain'


def test_rescoring_changes_only_target_and_rejects_changed_question(review_files):
    _, _, original, _ = review_files
    prediction = {'id': original['id'], 'group_id': original['family'], 'expected': 'abstain',
                  'text_sha256': original['text_sha256'], 'selected': 'privacy', 'probabilities': {'privacy': 1.0}}
    corrected = {**original, 'expected': 'privacy'}
    rescored = rescore_rows([prediction], [original], [corrected])[0]
    assert rescored == {**prediction, 'expected': 'privacy'} and prediction['expected'] == 'abstain'
    with pytest.raises(ValueError, match='unchanged original'):
        rescore_rows([prediction], [original], [{**corrected, 'text': 'Otro texto'}])
