# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import hydra.api.client_keys as client_keys
from hydra.api.client_keys import client_route, new_credential
from hydra.api.security import authenticate


def registry(path, *rows):
    path.write_text(json.dumps({'clients': list(rows)}))


def client_row(client_id, record, **extra):
    return {'id': client_id, **record, 'enabled': True, 'requests_per_minute': 30, **extra}


def test_client_keys_revocation_and_scope(tmp_path):
    path = tmp_path / 'keys.json'
    token, record = new_credential()
    row = client_row('celtia', record)
    registry(path, row)
    settings = SimpleNamespace(client_keys_file=path, api_key='operator')
    assert authenticate(settings, '10.0.0.2', token) == 'client:celtia'
    client_route('client:celtia', 'POST', '/v1/chat/completions')
    for route in ['/hydra/v1/goals', '/hydra/v1/edge/sync/import', '/v1/hydra']:
        with pytest.raises(HTTPException) as error:
            client_route('client:celtia', 'POST', route)
        assert error.value.status_code == 403
    row['enabled'] = False
    registry(path, row)
    with pytest.raises(HTTPException):
        authenticate(settings, '127.0.0.1', token)


def test_registry_never_stores_the_secret_and_wrong_secrets_fail(tmp_path):
    path = tmp_path / 'keys.json'
    token, record = new_credential()
    registry(path, client_row('nova-ai', record))
    secret = token.rsplit('.', 1)[1]
    assert secret not in path.read_text() and 'sha256' not in path.read_text()
    assert record['scrypt']['n'] >= 2 ** 14 and len(bytes.fromhex(record['scrypt']['salt'])) == 16
    forged = token[:-4] + ('AAAA' if not token.endswith('AAAA') else 'BBBB')
    assert client_keys.lookup(path, forged) is None
    assert client_keys.lookup(path, token)['id'] == 'nova-ai'


def test_verification_is_cached_but_follows_rotation(tmp_path, monkeypatch):
    path = tmp_path / 'keys.json'
    token, record = new_credential()
    registry(path, client_row('celtia', record))
    calls = []
    real = client_keys._matches
    monkeypatch.setattr(client_keys, '_matches', lambda row, secret: calls.append(1) or real(row, secret))
    for _ in range(3):
        assert client_keys.lookup(path, token)['id'] == 'celtia'
    assert len(calls) == 1  # one scrypt per process, constant-time comparison afterwards
    # Rotation replaces the registry entry: the old credential must stop working at once.
    _, rotated = new_credential()
    rotated['key_id'] = record['key_id']
    registry(path, client_row('celtia', rotated))
    assert client_keys.lookup(path, token) is None


def test_legacy_sha256_rows_are_not_accepted(tmp_path):
    path = tmp_path / 'keys.json'
    registry(path, {'id': 'celtia', 'sha256': 'a' * 64, 'enabled': True})
    settings = SimpleNamespace(client_keys_file=path, api_key='')
    with pytest.raises(HTTPException) as error:
        authenticate(settings, '10.0.0.2', 'hydra_legacy-format-token')
    assert error.value.status_code == 401


def test_rotate_reissues_legacy_clients(tmp_path):
    from scripts.manage_client_keys import provision

    path, delivery = tmp_path / 'keys.json', tmp_path / 'delivery'
    registry(path, {'id': 'celtia', 'sha256': 'a' * 64, 'enabled': True, 'requests_per_minute': 12,
                    'scope': 'inference'})
    provision('celtia', 30, rotate=True, registry=path, delivery_dir=delivery)
    row = json.loads(path.read_text())['clients'][0]
    assert 'sha256' not in row and row['requests_per_minute'] == 12 and row['enabled']
    token = (delivery / 'celtia.env').read_text().split('HYDRA_API_KEY=')[1].strip()
    assert client_keys.lookup(path, token)['id'] == 'celtia'
    with pytest.raises(ValueError, match='Unknown client'):
        provision('nobody', 30, rotate=True, registry=path, delivery_dir=delivery)


def test_unknown_token_does_not_gain_local_access(tmp_path):
    settings = SimpleNamespace(client_keys_file=tmp_path / 'missing', api_key='')
    with pytest.raises(HTTPException) as error:
        authenticate(settings, '127.0.0.1', 'wrong')
    assert error.value.status_code == 401
    assert authenticate(settings, '127.0.0.1', None).startswith('local:')


def test_gateway_blocks_client_before_admin_or_task_execution(tmp_path):
    from fastapi.testclient import TestClient
    from hydra.api.main import create_app
    from hydra.core.config import Settings

    path = tmp_path / 'clients.json'
    token, record = new_credential()
    registry(path, client_row('nova-ai', record))
    settings = Settings(client_keys_file=path, api_key='', admin_token='', runtime_api=False)
    # No lifespan: blocked requests must never reach the engine or its state.
    client = TestClient(create_app(settings))
    response = client.post('/hydra/v1/goals', headers={'X-API-Key': token}, json={'goal': 'do something'})
    assert response.status_code == 403
    assert response.json()['detail'] == 'client key permits inference only'
