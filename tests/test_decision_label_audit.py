# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json

import pytest

from hydra.router.decision_contract import CRITERIA
from hydra.training.decision_label_audit import prepare


@pytest.fixture
def inputs(tmp_path):
    originals, predictions = [], []
    for index, label in enumerate(('privacy', 'abstain')):
        text = 'Fixture sintética de revisión ' + str(index)
        row = {'id': str(index), 'text': text, 'expected': label,
               'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
        originals.append(row)
        predictions.append({**row, 'group_id': 'scenario-' + str(index), 'selected': 'abstain',
                            'probabilities': {k: float(k == 'abstain') for k in CRITERIA}})
    corpus, evidence = tmp_path / 'corpus.jsonl', tmp_path / 'comparison.json'
    corpus.write_text(''.join(json.dumps(r) + '\n' for r in originals), encoding='utf-8')
    evidence.write_text(json.dumps({'format': 'hyd-kev-paired/1', 'complete': True,
                                   'hyd_rows': predictions, 'kev_rows': predictions}), encoding='utf-8')
    return corpus, evidence


def test_review_keeps_agreements_and_hides_labels_and_predictions(inputs, tmp_path):
    corpus, evidence = inputs
    before = corpus.read_bytes()
    result = prepare(corpus, [evidence], tmp_path / 'review')
    assert result['review_rows'] == 2 and result['priority_rows'] == 1
    assert corpus.read_bytes() == before
    rows = [json.loads(line) for line in (tmp_path / 'review/review-blind.jsonl').read_text().splitlines()]
    assert all(r['human_label'] is None and not r['confirmed'] and not r['training_allowed'] for r in rows)
    assert all('expected' not in r and 'predictions' not in r for r in rows)


def test_review_rejects_changed_original_text(inputs, tmp_path):
    corpus, evidence = inputs
    rows = corpus.read_text().splitlines()
    first = json.loads(rows[0])
    first['text'] += ' modificado'
    rows[0] = json.dumps(first)
    corpus.write_text('\n'.join(rows), encoding='utf-8')
    with pytest.raises(ValueError, match='original corpus'):
        prepare(corpus, [evidence], tmp_path / 'review')


def test_review_rejects_double_counting(inputs, tmp_path):
    corpus, evidence = inputs
    with pytest.raises(ValueError, match='one comparison only'):
        prepare(corpus, [evidence, evidence], tmp_path / 'review')
