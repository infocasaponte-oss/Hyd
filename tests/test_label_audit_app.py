# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json
import re

from fastapi.testclient import TestClient

from hydra.api.label_audit_app import create_app


def test_human_review_persists_and_exports_history_without_changing_original(tmp_path):
    row = {'id': 'synthetic-case', 'text': '<script>Fixture sintética</script>',
           'text_sha256': 'fixture', 'human_label': None, 'training_allowed': False}
    queue = tmp_path / 'review-blind.jsonl'
    original = json.dumps(row).encode()
    queue.write_bytes(original)
    manifest = {'format': 'hyd-label-review/1', 'priority_rows': 1, 'source_sha256': 'fixture-source',
                'files': {queue.name: hashlib.sha256(original).hexdigest()}}
    (tmp_path / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    app = create_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        page = client.get('/')
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        token = re.search(r"token='([a-f0-9]+)'", page.text).group(1)
        payload = {'case_id': row['id'], 'human_label': 'privacy', 'reviewer': 'Synthetic reviewer'}
        assert client.post('/api/review', json=payload).status_code == 403
        assert client.get('/api/cases', headers={'Host': 'external.invalid'}).status_code == 403
        headers = {'X-Review-Token': token}
        assert client.post('/api/review', headers=headers, json=payload).status_code == 200
        assert client.post('/api/review', headers=headers, json={**payload, 'human_label': 'ambiguous'}).status_code == 422
        assert client.post('/api/review', headers=headers, json={**payload, 'human_label': 'abstain', 'notes': 'Revisión humana confirmada'}).status_code == 200
        exported = [json.loads(line) for line in client.get('/api/export').text.splitlines()]
        assert [e['human_label'] for e in exported] == ['privacy', 'abstain']
        assert all(e['confirmed'] and not e['training_allowed'] for e in exported)
        assert queue.read_bytes() == original
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as restarted:
        assert restarted.get('/api/cases').json()['reviews'][row['id']]['human_label'] == 'abstain'
