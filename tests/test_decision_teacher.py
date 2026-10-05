# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json
from pathlib import Path

import pytest

from hydra.router.decision_contract import CRITERIA
from hydra.training.decision_active_learning import read_rows
from hydra.training.decision_teacher import experimental_snapshot, review
from hydra.training.decision_balanced_examples import generate


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    paths, proposals = {}, []
    for split in ('fit', 'dev', 'cal_prob', 'cal_policy', 'test'):
        rows = []
        for index, label in enumerate(CRITERIA):
            text = f'Fixture sintética {split} {index}'
            row = {'id': split + '-' + label, 'text': text, 'expected': label,
                   'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                   'group_id': split + '-scenario-' + str(index), 'training_allowed': split == 'fit'}
            if split == 'fit' and label == 'privacy':
                row['label_review'] = {'human_label': 'privacy', 'reviewer': 'Synthetic reviewer'}
            rows.append(row)
            proposals.append({'id': row['id'], 'text_sha256': row['text_sha256'],
                              'proposed_label': list(CRITERIA)[(index + 1) % 10],
                              'label_source': 'local_ai_proposal', 'human_confirmed': False})
        path = root / (split + '.jsonl')
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        paths[split] = str(path)
    # Keep all ten fit labels represented while disagreeing with one confirmed human.
    for row in proposals:
        if row['id'].startswith('fit-') and row['id'] != 'fit-privacy':
            row['proposed_label'] = row['id'][4:]
    (root / 'manifest.json').write_text(json.dumps({'paths': paths}), encoding='utf-8')
    target = tmp_path / 'proposals.jsonl'
    target.write_text(''.join(json.dumps(r) + '\n' for r in proposals), encoding='utf-8')
    return root, target, paths


def test_teacher_never_changes_evaluation_or_confirmed_human(snapshot, tmp_path):
    root, target, original = snapshot
    paths = experimental_snapshot(root, target, tmp_path / 'experiment')
    for split in ('dev', 'cal_prob', 'cal_policy', 'test'):
        assert Path(paths[split]).read_bytes() == Path(original[split]).read_bytes()
    rows = read_rows(Path(paths['fit']))
    assert next(r for r in rows if r['id'] == 'fit-privacy')['expected'] == 'privacy'
    assert not json.loads((tmp_path / 'experiment/manifest.json').read_text())['authority']


def test_teacher_rejects_changed_question_binding(snapshot, tmp_path):
    root, target, _ = snapshot
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    rows[0]['text_sha256'] = 'changed'
    target.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    with pytest.raises(ValueError, match='another question'):
        experimental_snapshot(root, target, tmp_path / 'experiment')
    assert not (tmp_path / 'experiment').exists()


def test_synthetic_balance_is_declared_and_never_overlaps_reserved_inputs(snapshot, tmp_path):
    root, target, original = snapshot
    generated = tmp_path / 'generated'
    generate(generated)
    synthetic = generated / 'balanced-examples.jsonl'
    rows = read_rows(synthetic)
    from collections import Counter
    assert Counter(r['expected'] for r in rows) == {label: 24 for label in CRITERIA}
    traps = read_rows(generated / 'contrast-traps.jsonl')
    assert all(r['expected'] is None and not r['human_confirmed'] for r in traps)
    # A synthetic proposal identical to a held-out question must never enter fit.
    held = read_rows(Path(original['test']))[0]
    collision = {**rows[0], 'text': held['text'], 'text_sha256': held['text_sha256']}
    synthetic.write_text(''.join(json.dumps(r) + '\n' for r in [collision, *rows]), encoding='utf-8')
    paths = experimental_snapshot(root, target, tmp_path / 'experiment', synthetic)
    fit = read_rows(Path(paths['fit']))
    assert all(r['text'] != held['text'] for r in fit)
    assert Path(paths['test']).read_bytes() == Path(original['test']).read_bytes()
    meta = json.loads((tmp_path / 'experiment/manifest.json').read_text())
    assert meta['synthetic_collisions_skipped'] == 1 and meta['synthetic_examples_added_to_fit'] == 240


def mock_teacher(monkeypatch, reply, *, done_reason='stop'):
    import httpx
    original_client = httpx.Client
    calls = []

    def respond(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'fixture:latest', 'digest': 'fixed-digest'}]})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'message': {'content': json.dumps(reply)},
                                      'done': True, 'done_reason': done_reason})

    monkeypatch.setattr('hydra.training.decision_teacher.httpx.Client',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    return calls


def teacher_corpus(tmp_path):
    text = 'Exemplo sintético para comprobar a revisión local'
    path = tmp_path / 'teacher-corpus.jsonl'
    path.write_text(json.dumps({'id': 'synthetic-fixture', 'text': text,
                               'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                               'consent': True, 'rights': 'synthetic test fixture'}) + '\n', encoding='utf-8')
    return path


def test_single_protocol_records_actual_reply_and_resumes_without_inference(tmp_path, monkeypatch):
    calls = mock_teacher(monkeypatch, {'label': 'chat'})
    source = teacher_corpus(tmp_path)
    out = tmp_path / 'teacher'
    first = review(source, out, model='fixture:latest', single=True)
    second = review(source, out, model='fixture:latest', single=True)
    assert first == second and len(calls) == 1
    assert calls[0]['messages'][1]['content'] == read_rows(source)[0]['text']
    assert first['binding']['protocol'] == 'single-label/3'
    proposals = read_rows(out / 'proposals.jsonl')
    assert proposals[0]['proposed_label'] == 'chat'
    assert proposals[0]['human_confirmed'] is False and not proposals[0]['training_allowed']
    recorded = json.loads((out / 'batch-0000.json').read_text())
    assert recorded['actual_response']['message']['content'] == json.dumps({'label': 'chat'})
    (out / 'batch-0000.json').write_text('{}')
    with pytest.raises(ValueError, match='response changed'):
        review(source, out, model='fixture:latest', single=True)


@pytest.mark.parametrize('reply', [
    {'results': [{'i': False, 'label': 'chat', 'reason': 'A label'}]},
    {'results': [{'i': 0, 'label': 'chat', 'reason': None}]},
])
def test_audited_protocol_rejects_malformed_identity_and_reason(tmp_path, monkeypatch, reply):
    mock_teacher(monkeypatch, reply)
    out = tmp_path / 'teacher'
    with pytest.raises(ValueError):
        review(teacher_corpus(tmp_path), out, model='fixture:latest', audited=True)
    assert not (out / 'proposals.jsonl').exists()
    assert not list(out.glob('batch-*.json'))


def test_truncated_single_reply_is_never_admitted(tmp_path, monkeypatch):
    mock_teacher(monkeypatch, {'label': 'chat'}, done_reason='length')
    out = tmp_path / 'teacher'
    with pytest.raises(ValueError, match='incomplete'):
        review(teacher_corpus(tmp_path), out, model='fixture:latest', single=True)
    assert not (out / 'proposals.jsonl').exists()


def test_synthetic_only_experiment_preserves_every_existing_fit_label(snapshot, tmp_path):
    root, _, original = snapshot
    generated = tmp_path / 'generated'
    generate(generated)
    paths = experimental_snapshot(root, None, tmp_path / 'experiment', generated / 'balanced-examples.jsonl')
    before = read_rows(Path(original['fit']))
    after = read_rows(Path(paths['fit']))
    assert after[:len(before)] == before
    assert len(after) == len(before) + 240
    meta = json.loads((tmp_path / 'experiment/manifest.json').read_text())
    assert meta['proposals_sha256'] is None and meta['fit_label_changes'] == 0
    for split in ('dev', 'cal_prob', 'cal_policy', 'test'):
        assert Path(paths[split]).read_bytes() == Path(original[split]).read_bytes()
