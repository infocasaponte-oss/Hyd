# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Real, isolated HYDRA/Hyd/worker smoke run. Requires installed encoder and Ollama."""
import argparse
import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from hydra.training.evidence_io import write_json


async def run(candidate, out, model, endpoint):
    if out.exists() or urlparse(endpoint).hostname not in ('localhost', '127.0.0.1'):
        raise ValueError('new output and loopback Ollama required')
    out.mkdir(parents=True)
    # These affect only this probe process. No existing runtime or database is adopted.
    os.environ['HYDRA_RUNTIME_DIR'] = str(out / 'runtime')
    os.environ['HYDRA_RUNTIME_BACKEND'] = 'file'
    os.environ['HYDRA_KEY_BACKEND'] = 'legacy'
    from hydra.core.bootstrap import build_runtime
    from hydra.core.config import Settings
    from hydra.core.contracts import HydraRequest, Message
    from hydra.providers.ollama import OllamaProvider
    from hydra.registry.models import ModelProfile, Capabilities, ModelQuirks
    from hydra.registry.registry import ModelRegistry
    from hydra.tools.sandbox import SubprocessSandbox

    def identity():
        reply = httpx.get(endpoint + '/api/tags', timeout=10)
        reply.raise_for_status()
        return next(r['digest'] for r in reply.json()['models'] if r['name'] == model)

    digest = identity()
    provider = OllamaProvider(endpoint)
    profile = ModelProfile(id='local-smoke-model', provider='ollama', runtime_model=model,
        local=True, context_window=4096, capabilities=Capabilities(chat=.7, reasoning=.7, coding=.7, tools=.7),
        runtime_options={'num_ctx': 4096, 'num_predict': 384, 'temperature': 0, 'seed': 42, 'think': False},
        quirks=ModelQuirks(native_tools=False))
    settings = Settings(_env_file=None, offline=False, postgres_url='', redis_url='', nats_url='',
        runtime_monitor=False, memory_backend='sqlite', key_backend='legacy',
        workspace_dir=out / 'workspace', data_dir=out / 'data', runtime_dir=str(out / 'runtime'),
        public_web_enabled=False, cloud_api_key='', sandbox_backend='subprocess',
        hyd_enabled=True, hyd_model_path=candidate / 'model.json',
        hyd_calibration_path=candidate / 'calibration.json', hyd_authority_evidence_path=None,
        hyd_fallback_model_path=None, hyd_fallback_calibration_path=None)
    profiles = [profile.model_copy(update={'logical_model': model}),
                profile.model_copy(update={'id': 'local-smoke-reviewer', 'logical_model': model})]
    runtime = await build_runtime(settings, providers={'ollama': provider},
                                  registry=ModelRegistry(profiles), sandbox=SubprocessSandbox())
    (settings.workspace_dir / 'fixture.txt').write_text('HYDRA_SMOKE_READ_ONLY_FIXTURE', encoding='utf-8')
    events = []

    async def record(event):
        events.append(event.model_dump(mode='json'))

    await runtime.bus.subscribe(None, record)
    report = {'format': 'hydra-hyd-real-smoke/1', 'complete': False, 'authority': False,
              'promotion_ready': False, 'model': model, 'model_digest': digest,
              'mock_provider_used': False, 'independent_model_votes': False,
              'cases_are_synthetic': True, 'corpus_accuracy_benchmark': False,
              'hyd_encoder_ready_at_startup': getattr(runtime.kernel.router.observer, 'encoder_ready', False),
              'cases': []}
    cases = [
        ('chat', 'Redacta en galego unha felicitación breve para un club de lectura ficticio.'),
        ('reasoning-and-critic', 'Razona y demuestra cuántas piezas hay en total: doce cajas con tres piezas cada una, y seis piezas sueltas. '
         + ' '.join(f'Condición {i}: cada caja contiene exactamente tres piezas; las seis piezas sueltas se cuentan una sola vez.' for i in range(1, 27))
         + ' Calcula el total y comprueba el razonamiento, sin consultar fuentes externas.'),
        ('tools-and-coder', 'Lee el archivo fixture.txt de la carpeta de trabajo de esta prueba y devuelve su contenido exacto. Usa solamente lectura; no ejecutes código ni modifiques archivos.'),
    ]
    try:
        for name, text in cases:
            print('HYDRA real probe: ' + name, flush=True)
            start = len(events)
            request = HydraRequest(messages=[Message(role='user', content=text)],
                                   mode='max' if name == 'reasoning-and-critic' else 'balanced',
                                   local_only=True, use_cache=False)
            try:
                response = await asyncio.wait_for(runtime.kernel.run(request, shadow=True, learn=False), 90)
                result = response.model_dump(mode='json')
                case = {'name': name, 'response': result, 'completed_without_exception': True}
                if name == 'reasoning-and-critic':
                    case['known_answer'] = 42
                    case['contains_known_answer'] = bool(re.search(r'\b42\b', response.answer))
                elif name == 'tools-and-coder':
                    case['fixture_content_reported'] = 'HYDRA_SMOKE_READ_ONLY_FIXTURE' in response.answer
            except Exception as exc:
                case = {'name': name, 'completed_without_exception': False, 'error_type': type(exc).__name__}
            case['actual_events'] = events[start:]
            case['actual_worker_roles'] = sorted({e['payload']['role'] for e in events[start:]
                                                  if e['type'] == 'model.completed'})
            case['actual_hyd_observations'] = [e['payload'].get('observation') for e in events[start:]
                                              if e['type'] == 'route.selected']
            report['cases'].append(case)
            write_json(out / 'report.json', report)
        report['complete'] = True
        report['same_model_digest_after'] = identity() == digest
        report['limitation'] = 'Hyd is attached in observation because it has no promotion evidence. Worker roles use one physical model, not independent votes. A smoke run does not establish 90% accuracy.'
        write_json(out / 'report.json', report)
    finally:
        await runtime.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--endpoint', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    asyncio.run(run(args.candidate, args.out, args.model, args.endpoint))


if __name__ == '__main__':
    main()
