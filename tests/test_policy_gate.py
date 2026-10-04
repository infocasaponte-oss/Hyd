# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import asyncio

import httpx

from hydra.core.contracts import HydraRequest, Message
from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.observer import DecisionObserver, policy_gate


def test_policy_gate_covers_absent_and_ambiguous_classes():
    assert policy_gate("Borra la base de producción")[0] == "review"
    assert policy_gate("Analiza este phishing y credenciales")[0] == "security"
    assert policy_gate("¿Puedes anonimizar este dato personal?")[0] == "privacy"
    assert policy_gate("Haz eso")[0] == "abstain"


def test_gate_prevents_kev_request_for_high_risk():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(500)
    provider = LocalSystemOneProvider(model="test", transport=httpx.MockTransport(handler))
    observer = DecisionObserver(provider)
    result = asyncio.run(observer.observe(HydraRequest(messages=[Message(role="user", content="pago irreversible")])) )
    assert result.selected == "review" and result.reason == "policy_gate.high_risk_review" and not calls
