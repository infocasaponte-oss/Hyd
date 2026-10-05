# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Identical physical weights cannot masquerade as independent reviewers."""
from types import SimpleNamespace

import pytest

from hydra.blackboard.state import BlackboardState, Evidence
from hydra.core.budget import BudgetTracker, budget_for
from hydra.core.context import TaskContext
from hydra.core.contracts import HydraRequest, Message, RoutingDecision
from hydra.verification.verifier import Verifier


def fixture_state(supports=True):
    state = BlackboardState()
    state.evidence['vote'] = Evidence(id='vote', claim_id='claim', source_type='model',
                                      source_ref='alias', strength=.9, supports=supports)
    state.critiques.append({'model': 'alias', 'target': 'claim',
                           'verdict': 'pass' if supports else 'fail',
                           'score': .9 if supports else .1, 'issues': []})
    return state


def verify(state, dependent):
    request = HydraRequest(messages=[Message(role='user', content='Synthetic greeting task')])
    route = RoutingDecision(task_type='chat', complexity=.2, risk=0)
    return Verifier().verify(request, route, state, 'Synthetic greeting', claim_id='claim',
                             dependent_models=dependent)


def test_correlated_positive_votes_never_verify():
    result = verify(fixture_state(), {'alias'})
    assert result.passed and not result.verified and not result.independent
    assert result.evidence is None and result.confidence_signal <= .65


def test_correlated_negative_review_still_rejects():
    result = verify(fixture_state(False), {'alias'})
    assert not result.passed and not result.verified and not result.independent


def test_distinct_reviewer_can_supply_independent_layer():
    result = verify(fixture_state(), {'author'})
    assert result.verified and result.independent


async def test_kernel_excludes_same_weights_even_with_different_logical_aliases(runtime):
    runtime.registry.models['small'].runtime_model = 'identical-weights:latest'
    runtime.registry.models['small'].logical_model = 'declared-family-A'
    runtime.registry.models['medium'].runtime_model = 'identical-weights'
    runtime.registry.models['medium'].logical_model = 'declared-family-B'
    request = HydraRequest(messages=[Message(role='user', content='Synthetic greeting task')])
    ctx = TaskContext(request=request, bus=runtime.bus, budget=BudgetTracker(budget_for(request)))
    ctx.route = RoutingDecision(task_type='chat', complexity=.2, risk=0)
    ctx.state = fixture_state()
    ctx.state.evidence['vote'].source_ref = 'medium'
    ctx.state.critiques[0]['model'] = 'medium'
    ctx.state.candidates = [{'claim_id': 'claim', 'model': 'small', 'answer': 'Synthetic greeting'},
                            {'claim_id': 'other', 'model': 'medium', 'answer': 'Synthetic greeting'}]
    result, _ = await runtime.kernel._verify(ctx, ctx.state.candidates[0], None)
    assert not result.verified and not result.independent and result.evidence is None


@pytest.mark.parametrize('cache_available', [True, False])
async def test_bootstrap_prepares_encoder_or_reports_degraded_readiness(settings, mock, monkeypatch, cache_available):
    from hydra.core.bootstrap import build_runtime
    from hydra.registry.registry import ModelRegistry
    from hydra.tools.sandbox import SubprocessSandbox
    from .conftest import default_models
    calls = []

    def vectors(texts):
        calls.extend(texts)
        if not cache_available:
            raise RuntimeError('Synthetic unavailable encoder cache')

    class Observer:
        def __init__(self, *args, **kwargs):
            self.engine = SimpleNamespace(ranker=SimpleNamespace(spec={'kind': 'minilm'}, vectors=vectors))

        async def close(self):
            pass

    monkeypatch.setattr('hydra.hyd.continual_controller.controller_class', lambda path: Observer)
    settings.offline = False
    settings.runtime_monitor = False
    if hasattr(settings, 'hyd_fallback_model_path'):
        settings.hyd_fallback_model_path = None
    runtime = await build_runtime(settings, providers={'mock': mock, 'mock-cloud': mock},
                                  registry=ModelRegistry(default_models()), sandbox=SubprocessSandbox())
    try:
        assert calls and runtime.kernel.router.observer.encoder_ready is cache_available
        assert runtime.kernel.router.observer is runtime.kernel.router.authority
    finally:
        await runtime.close()
