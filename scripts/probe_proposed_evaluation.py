# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Preserve review data and probe supplied questions without inventing human votes."""
import asyncio
import json
from pathlib import Path

import httpx

from hydra.training.evaluate_corpus import candidate_hash, model_identity
from hydra.training.evidence_io import write_json
from hydra.training.verified_corpus import sha256


async def main():
    attachment = Path('C:/Users/mejil/.codex/attachments/cfc57d4e-fe9f-47f9-bc3d-77cd20993020/Texto pegado.txt')
    text = attachment.read_text(encoding='utf-8-sig')
    section = text.split('1. NUEVO SET DE PREGUNTAS', 1)[1].split('2. SCHEMA SQL', 1)[0]
    prompts = [line.strip()[1:-1] for line in section.splitlines()
               if line.strip().startswith('“') and line.strip().endswith('”')]
    if len(prompts) != 20 or len(set(prompts)) != 20:
        raise ValueError('Expected twenty distinct supplied questions')
    root = Path('docs/evidence/proposed-evaluation-2026-10-01')
    if root.exists():
        raise FileExistsError('Preserve previous evidence; choose a new run directory')
    root.mkdir(parents=True)
    review_path = Path('C:/Users/mejil/Downloads/hydra-mi-revision.json')
    review = json.loads(review_path.read_text(encoding='utf-8-sig'))
    dataset = Path('data/external-evaluation-v2/cases.json')
    answers_path = Path('docs/evidence/external-evaluation-v7.json')
    answers = json.loads(answers_path.read_text(encoding='utf-8'))
    if review['dataset_sha256'] != sha256(dataset) or review['artifact_sha256'] != answers['artifact_sha256']:
        raise ValueError('Review binding mismatch')
    rows = {str(row['id']): row for row in json.loads(dataset.read_text(encoding='utf-8-sig'))}
    outputs = {str(row['id']): row for row in answers['cases']}
    normalized = dict(eval_id='human-review-v7-normalized', artifact_sha256=review['artifact_sha256'],
                      dataset_sha256=review['dataset_sha256'], source_sha256=sha256(review_path),
                      approved=False, cases=[])
    for key, vote in review['cases'].items():
        normalized['cases'].append(dict(vote, input=rows[key]['prompt'],
            expected_output=rows[key]['expected_response'], model_output=outputs[key]['output'],
            task_category=None, error_type=None, severity=None, reason_category=None, action_hint=None))
    write_json(root/'normalized-review.json', normalized)
    cases = [dict(id=i, prompt=prompt, decision=None, expected_response=None,
                  requires_human_review=True) for i, prompt in enumerate(prompts, 1)]
    write_json(root/'cases.json', dict(cases=cases, source_sha256=sha256(attachment), frozen=True,
                                     scope='Exploratory; no training or promotion'))
    digest = candidate_hash(Path('models/hydra-instruction-v7/build-manifest.json'))
    result = dict(model='hydra-instruction-v7:latest', artifact_sha256=digest,
                  dataset_sha256=sha256(root/'cases.json'), complete=False, approved=False,
                  independent_test=False, cases=[])
    async with httpx.AsyncClient(base_url='http://127.0.0.1:11434', timeout=120) as client:
        identity = await model_identity(client, result['model'], digest)
        result['identity'] = identity
        for case in cases:
            record = dict(case)
            try:
                response = await client.post('/api/chat', json=dict(model=result['model'], stream=False,
                    messages=[dict(role='system', content='Eres HYDRA. Sigue la instrucción del usuario sin añadir datos no proporcionados.'),
                              dict(role='user', content=case['prompt'])],
                    options=dict(temperature=0, seed=42, num_ctx=2048, num_predict=220, num_gpu=99),
                    keep_alive='5m'))
                response.raise_for_status()
                data = response.json()
                record.update(model_output=data['message']['content'], eval_count=data.get('eval_count'),
                              total_duration_ns=data.get('total_duration'))
            except (httpx.HTTPError, KeyError) as error:
                record['error'] = type(error).__name__
            result['cases'].append(record)
            write_json(root/'results.json', result)
            print(f"Case {case['id']}/20: {'error' if 'error' in record else 'response'}", flush=True)
        if identity != await model_identity(client, result['model'], digest):
            raise ValueError('Model changed during evaluation')
        response = await client.get('/api/ps')
        response.raise_for_status()
        result['runtime_models'] = response.json()
    result.update(complete=True, errors=sum('error' in case for case in result['cases']))
    write_json(root/'results.json', result)


if __name__ == '__main__':
    asyncio.run(main())
