# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Trust plane: identities, capability-based security, action envelopes and the Risk Engine.

    LLM -> proposal -> ActionEnvelope -> Policy Kernel (identity, authorization, risk) -> Executor

The model is never the authority. Instead of ``can_use_tools = true`` every principal
holds explicit, least-privilege capability tokens such as::

    filesystem.read:/workspace/project/**     database.read:analytics
    network.connect:api.example.com           model.use:local        gpu.allocate:interactive

Risk:  R = w_d·D + w_e·E + w_p·P + w_f·F + w_i·I
       (destructiveness, external effect, privacy, financial cost, irreversibility)
       R < 0.20 allow · R < 0.45 stronger verification · otherwise explicit authorization."""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import json
import time
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Principal(BaseModel):
    id: str
    principal_type: str = "user"  # user | agent | model | service | tool | worker
    tenant_id: str | None = None
    roles: set[str] = Field(default_factory=set)
    capabilities: set[str] = Field(default_factory=set)
    trust_level: int = 1


def capability_matches(granted: str, requested: str) -> bool:
    """``filesystem.read:/workspace/**`` grants ``filesystem.read:/workspace/a/b.py``."""
    g_action, _, g_scope = granted.partition(":")
    r_action, _, r_scope = requested.partition(":")
    if not fnmatch.fnmatchcase(r_action, g_action):
        return False
    if not g_scope or g_scope == "*":
        return True
    if g_scope.endswith("/**"):
        base = g_scope[:-3]
        return r_scope == base or r_scope.startswith(base.rstrip("/") + "/")
    return fnmatch.fnmatchcase(r_scope, g_scope)


def has_capability(principal: Principal | set[str], requested: str) -> bool:
    caps = principal.capabilities if isinstance(principal, Principal) else principal
    return any(capability_matches(g, requested) for g in caps)


class CapabilityToken(BaseModel):
    """A signed, expiring grant handed to a worker (it can only do what the token says)."""

    token_id: str = Field(default_factory=lambda: uuid4().hex)
    principal_id: str
    capabilities: list[str]
    task_id: str | None = None
    expires_at: float
    signature: str = ""


class TokenAuthority:
    def __init__(self, secret: bytes) -> None:
        self.secret = secret

    def _sig(self, t: CapabilityToken) -> str:
        body = json.dumps(t.model_dump(exclude={"signature"}), sort_keys=True).encode()
        return base64.urlsafe_b64encode(hmac.new(self.secret, body, hashlib.sha256).digest()).decode()

    def issue(self, principal_id: str, capabilities: list[str], ttl_s: float = 600, task_id: str | None = None
              ) -> CapabilityToken:
        t = CapabilityToken(principal_id=principal_id, capabilities=sorted(set(capabilities)), task_id=task_id,
                            expires_at=time.time() + ttl_s)
        t.signature = self._sig(t)
        return t

    def verify(self, t: CapabilityToken, requested: str) -> bool:
        return (hmac.compare_digest(t.signature, self._sig(t)) and t.expires_at > time.time()
                and any(capability_matches(g, requested) for g in t.capabilities))


class ActionRisk(BaseModel):
    destructive: float = 0.0
    external_side_effect: float = 0.0
    privacy_effect: float = 0.0
    financial_effect: float = 0.0
    irreversibility: float = 0.0
    estimated_recovery_cost: float = 0.0

    @property
    def reversible(self) -> bool:
        return self.irreversibility < 0.5


class RiskDecision(str, Enum):
    ALLOW = "allow"
    VERIFY = "require_stronger_verification"
    AUTHORIZE = "require_explicit_authorization"
    DENY = "deny"


class ActionEnvelope(BaseModel):
    action_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    principal_id: str
    task_id: str | None = None
    capability: str
    target: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk: ActionRisk = Field(default_factory=ActionRisk)
    risk_level: float = 0.0
    reversible: bool = True
    authorization_ref: str | None = None
    sandboxed: bool = False


ACTION_PROFILES: dict[str, ActionRisk] = {
    "filesystem.read": ActionRisk(),
    "workspace.read": ActionRisk(),
    "workspace.list": ActionRisk(),
    "workspace.search": ActionRisk(),
    "memory.search": ActionRisk(),
    "world.query": ActionRisk(),
    "json.validate": ActionRisk(),
    "sql.query_readonly": ActionRisk(privacy_effect=0.2),
    "python.execute": ActionRisk(destructive=0.1, irreversibility=0.05),
    "python.run_tests": ActionRisk(destructive=0.05),
    "http.fetch": ActionRisk(external_side_effect=0.2, privacy_effect=0.2),
    "filesystem.write": ActionRisk(destructive=0.4, irreversibility=0.2),
    "git.apply_patch": ActionRisk(destructive=0.5, irreversibility=0.2),
    "code.patch": ActionRisk(destructive=0.5, irreversibility=0.2),
    "model.reason": ActionRisk(),
    "service.restart": ActionRisk(destructive=0.6, external_side_effect=0.6, irreversibility=0.3),
    "database.migrate": ActionRisk(destructive=0.9, external_side_effect=0.5, irreversibility=0.9),
    "database.drop": ActionRisk(destructive=1.0, external_side_effect=0.8, irreversibility=1.0),
    "payment.send": ActionRisk(external_side_effect=1.0, financial_effect=1.0, irreversibility=1.0),
    "email.send": ActionRisk(external_side_effect=0.9, privacy_effect=0.6, irreversibility=1.0),
}


class RiskEngine:
    def __init__(self, weights: dict[str, float] | None = None, allow_below: float = 0.20,
                 verify_below: float = 0.45) -> None:
        self.w = weights or {"destructive": 0.3, "external_side_effect": 0.2, "privacy_effect": 0.15,
                             "financial_effect": 0.15, "irreversibility": 0.2}
        self.allow_below = allow_below
        self.verify_below = verify_below

    def profile(self, capability: str) -> ActionRisk:
        action = capability.split(":", 1)[0]
        return ACTION_PROFILES.get(action, ActionRisk(destructive=0.3, external_side_effect=0.3,
                                                      irreversibility=0.3))

    def score(self, risk: ActionRisk, sandboxed: bool = False) -> float:
        r = sum(self.w[k] * getattr(risk, k) for k in self.w)
        if sandboxed:  # a sandbox replica removes external effects and most irreversibility
            r *= 0.35
        return round(min(1.0, r / max(1e-9, sum(self.w.values()))), 4)

    def decide(self, env: ActionEnvelope) -> RiskDecision:
        env.risk = env.risk if env.risk != ActionRisk() else self.profile(env.capability)
        env.risk_level = self.score(env.risk, env.sandboxed)
        env.reversible = env.risk.reversible
        if env.risk_level < self.allow_below:
            return RiskDecision.ALLOW
        if env.risk_level < self.verify_below:
            return RiskDecision.VERIFY
        return RiskDecision.AUTHORIZE


class GateResult(BaseModel):
    allowed: bool
    decision: RiskDecision
    reason: str
    envelope: ActionEnvelope


class ActionGate:
    """Identity + capability + risk. Explicit authorizations are passed as action ids/capabilities."""

    def __init__(self, risk: RiskEngine | None = None, audit=None) -> None:
        self.risk = risk or RiskEngine()
        self.audit = audit  # callable(event_type, payload)

    def check(self, principal: Principal, env: ActionEnvelope, authorized: set[str] | None = None,
              verified: bool = False) -> GateResult:
        authorized = authorized or set()
        requested = f"{env.capability}:{env.target}" if env.target else env.capability
        if not has_capability(principal, requested):
            res = GateResult(allowed=False, decision=RiskDecision.DENY,
                             reason=f"missing capability {requested}", envelope=env)
        else:
            d = self.risk.decide(env)
            if d == RiskDecision.ALLOW:
                res = GateResult(allowed=True, decision=d, reason="low risk", envelope=env)
            elif d == RiskDecision.VERIFY:
                ok = verified or env.action_id in authorized or env.capability in authorized
                res = GateResult(allowed=ok, decision=d, reason="verified" if ok else "needs stronger verification",
                                 envelope=env)
            else:
                ok = env.action_id in authorized or env.capability in authorized
                env.authorization_ref = "explicit" if ok else None
                res = GateResult(allowed=ok, decision=d, reason="authorized" if ok else
                                 "needs explicit authorization", envelope=env)
        if self.audit is not None:
            self.audit("ACTION_GATE", {"principal": principal.id, "capability": env.capability, "target": env.target,
                                       "risk": env.risk_level, "decision": res.decision.value, "allowed": res.allowed})
        return res


DEFAULT_ROLE_CAPABILITIES: dict[str, set[str]] = {
    "admin": {"*"},
    "operator": {"filesystem.read:/**", "model.use:*", "gpu.allocate:*", "corpus.read:*", "world.query:*",
                 "python.execute", "python.run_tests", "json.validate", "memory.search", "model.reason"},
    "user": {"model.use:local", "model.use:cloud-approved", "model.reason", "world.query:*", "memory.search",
             "python.execute", "python.run_tests", "json.validate", "filesystem.read:/workspace/**"},
    "coder_worker": {"filesystem.read:/workspace/**", "filesystem.write:/workspace/**", "python.execute",
                     "python.run_tests", "git.apply_patch:/workspace/**", "code.patch:/workspace/**", "json.validate",
                     "model.reason", "workspace.list:*", "workspace.read:*", "workspace.search:*"},
    "research_worker": {"network.connect:*.wikipedia.org", "network.connect:arxiv.org", "http.fetch:*",
                        "memory.search", "model.reason", "world.query:*"},
}


def principal_for(principal_id: str, roles: set[str], tenant_id: str | None = None,
                  extra: set[str] | None = None) -> Principal:
    caps = set(extra or set())
    for r in roles:
        caps |= DEFAULT_ROLE_CAPABILITIES.get(r, set())
    return Principal(id=principal_id, roles=roles, tenant_id=tenant_id, capabilities=caps,
                     trust_level=3 if "admin" in roles else 2 if "operator" in roles else 1)
