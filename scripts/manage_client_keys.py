# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Provision, rotate or revoke application keys without displaying credentials.

The registry keeps only the key id and a salted scrypt hash; the credential itself is written once
to ``data/secrets/client-credentials/<client>.env`` for delivery. ``--rotate`` re-issues a client
(new key id and secret, same id, limit and scope): use it for clients created with the former
SHA-256 format, which the gateway no longer accepts."""
import argparse
import json
import re
from pathlib import Path

from hydra.api.client_keys import new_credential
from hydra.core.atomic import write_text_atomic

REGISTRY = Path('data/keys/api-clients.json')
DELIVERY = Path('data/secrets/client-credentials')


def provision(client, limit, revoke=False, rotate=False, registry=REGISTRY, delivery_dir=DELIVERY):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{1,63}', client) or not 1 <= limit <= 10000:
        raise ValueError('Invalid client ID or rate limit')
    if revoke and rotate:
        raise ValueError('Choose --revoke or --rotate, not both')
    delivery = Path(delivery_dir) / (client + '.env')
    registry = Path(registry)
    registry.parent.mkdir(parents=True, exist_ok=True)
    delivery.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {'clients': []}
    existing = next((row for row in data['clients'] if row['id'] == client), None)
    if revoke:
        if existing is None:
            raise ValueError('Unknown client')
        existing['enabled'] = False
    elif rotate:
        if existing is None:
            raise ValueError('Unknown client')
        token, record = new_credential()
        for legacy in ('sha256', 'key_id', 'scrypt'):
            existing.pop(legacy, None)
        existing.update(record, enabled=True)
        write_text_atomic(delivery, 'HYDRA_BASE_URL=http://127.0.0.1:18088/v1\nHYDRA_API_KEY=' + token + '\n')
    elif existing:
        raise ValueError('Client already exists; use --rotate to re-issue it or --revoke to disable it')
    else:
        if delivery.exists():
            raise ValueError('Credential file already exists')
        token, record = new_credential()
        write_text_atomic(delivery, 'HYDRA_BASE_URL=http://127.0.0.1:18088/v1\nHYDRA_API_KEY=' + token + '\n')
        data['clients'].append({'id': client, **record, 'enabled': True,
                                'requests_per_minute': limit, 'scope': 'inference'})
    write_text_atomic(registry, json.dumps(data, indent=2))
    print(json.dumps({'client': client, 'revoked': revoke, 'rotated': rotate,
                      'credential_file': str(delivery.resolve()), 'registry': str(registry.resolve())}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('client')
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--revoke', action='store_true')
    parser.add_argument('--rotate', action='store_true', help='re-issue the credential (new key id and secret)')
    args = parser.parse_args()
    provision(args.client, args.limit, args.revoke, args.rotate)
