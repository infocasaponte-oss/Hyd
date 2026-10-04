# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Automatic build-to-review pipeline. Human ratings are never manufactured."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from hydra.model_factory.build_hydra import build
from hydra.training.verified_corpus import sha256


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding='utf-8')
    temporary.replace(path)


def request(endpoint, path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(endpoint + path, data=payload,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def preload(config):
    """Pin every evaluation input before spending GPU time."""
    pins, suites = {}, []
    for item in config['suites']:
        path = Path(item['path'])
        digest = sha256(path)
        if digest != item['sha256']:
            raise ValueError(f'Evaluation input changed: {path}')
        source = path.read_text(encoding='utf-8')
        rows = json.loads(source) if path.suffix == '.json' else [
            json.loads(line) for line in source.splitlines() if line.strip()]
        if not rows:
            raise ValueError(f'Empty evaluation: {path}')
        ids = set()
        for row in rows:
            if row['id'] in ids:
                raise ValueError(f'Duplicate case ID: {path}')
            ids.add(row['id'])
            if 'messages' in row:
                if row['messages'][-1]['role'] != 'assistant':
                    raise ValueError('Missing reference answer')
            elif not row.get('prompt') or 'expected_response' not in row:
                raise ValueError('Missing evaluation question/reference')
        pins[str(path)] = digest
        suites.append((item, rows))
    if not suites:
        raise ValueError('No preloaded tests')
    return pins, suites


def run(config_path, check=False):
    config = json.loads(config_path.read_text(encoding='utf-8'))
    pins, suites = preload(config)
    recipe_path = Path(config['recipe'])
    if sha256(recipe_path) != config['recipe_sha256']:
        raise ValueError('Recipe changed; regenerate the factory bundle')
    server = Path(config['server'])
    if sha256(server) != config['server_sha256']:
        raise ValueError('Runtime changed')
    if check:
        return {'preloaded_cases': sum(len(rows) for _, rows in suites),
                'inputs': pins, 'approved': False}
    artifact_built = build(recipe_path)
    manifest_path = artifact_built.parent / 'build-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if str(manifest['status']).startswith('QUARANTINED'):
        raise ValueError('Quarantined model')
    artifact = Path(manifest['artifact']).resolve()
    if sha256(artifact) != manifest['sha256']:
        raise ValueError('Artifact changed')
    root = manifest_path.parent
    packet_path = root / 'human-review-packet.json'
    packet = {'artifact_sha256': manifest['sha256'], 'inputs': pins,
              'approved': False, 'status': 'AUTOMATIC_EVALUATION', 'cases': [],
              'rubric': ['instruction compliance', 'correctness', 'unsupported claims'],
              'human_correction_required': True, 'independent_test': False}
    save(packet_path, packet)
    port = int(config.get('port', 18092))
    endpoint = f'http://127.0.0.1:{port}'
    with (root / 'factory-runtime.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(server.resolve()), '-m', str(artifact),
            '--host', '127.0.0.1', '--port', str(port), '-ngl', '99',
            '-c', '2048', '--parallel', '1', '--jinja'], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 600
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Runtime exited; inspect factory-runtime.log')
                try:
                    request(endpoint, '/health')
                    break
                except (OSError, ValueError):
                    if time.monotonic() > deadline:
                        raise RuntimeError('Runtime readiness timeout')
                    time.sleep(1)
            props = request(endpoint, '/props')
            if Path(props.get('model_path', '')).resolve() != artifact:
                raise ValueError('Endpoint belongs to another model')
            packet['runtime_properties'] = props
            seen_questions = set()
            packet['duplicate_questions_skipped'] = 0
            for suite, rows in suites:
                for row in rows:
                    messages = row.get('messages', [{'role': 'user', 'content': row.get('prompt')},
                                                     {'role': 'assistant', 'content': row.get('expected_response')}])
                    question_key = json.dumps(messages, sort_keys=True, ensure_ascii=True)
                    if question_key in seen_questions:
                        packet['duplicate_questions_skipped'] += 1
                        continue
                    seen_questions.add(question_key)
                    start = time.monotonic()
                    response = request(endpoint, '/v1/chat/completions', {
                        'model': 'hydra', 'messages': messages[:-1], 'temperature': 0,
                        'seed': 42, 'max_tokens': 256})
                    output = response['choices'][0]['message']['content']
                    reference = messages[-1]['content']
                    packet['cases'].append({'suite': suite['path'], 'id': row['id'],
                        'messages': messages[:-1], 'reference': reference, 'output': output,
                        'exact_match': output.strip() == reference.strip(),
                        'latency_ms': (time.monotonic() - start) * 1000,
                        'human_rating': None, 'human_correction': None})
                    save(packet_path, packet)
            for name, digest in pins.items():
                if sha256(Path(name)) != digest:
                    raise ValueError('Evaluation input changed during run')
            if sha256(artifact) != manifest['sha256']:
                raise ValueError('Artifact changed during run')
            soak_start = time.monotonic()
            soak_count = int(config.get('soak_requests', 20))
            if soak_count < 1:
                raise ValueError('At least one stability request is required')
            for _ in range(soak_count):
                response = request(endpoint, '/v1/chat/completions', {
                    'model': 'hydra', 'messages': [{'role': 'user',
                        'content': 'Reply with exactly HYDRA'}],
                    'temperature': 0, 'max_tokens': 32})
                if not response['choices'][0]['message']['content'].strip():
                    raise ValueError('Empty stability response')
            packet['stability'] = {'requests': soak_count, 'errors': 0,
                                   'duration_seconds': time.monotonic() - soak_start,
                                   'scope': 'bounded smoke; not prolonged production soak'}
            packet.update(status='READY_FOR_HUMAN_CORRECTION', complete=True,
                          technical_failures=[], production_eligible=False,
                          calibration_status='PENDING_REAL_RESERVED_ROUTER_LOGITS',
                          prolonged_stability_status='NOT_EXECUTED')
            save(packet_path, packet)
        except Exception as error:
            packet.update(status='TECHNICAL_FAILURE', complete=False, error=str(error))
            save(packet_path, packet)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return {'review_packet': str(packet_path.resolve()), 'cases': len(packet['cases']),
            'status': packet['status'], 'approved': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.bundle, args.check), indent=2))
