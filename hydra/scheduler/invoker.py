# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Single entry point for model calls: budget, events, circuit breaker, typed retries,
fallback models and hedged requests."""

from __future__ import annotations

import asyncio
import logging

from hydra.core.budget import BudgetExceeded
from hydra.core.context import TaskContext
from hydra.core.contracts import ModelRequest, ModelResponse
from hydra.core.errors import ErrorKind, ModelError, RetryAction, decide
from hydra.core.events import EventType
from hydra.providers.adapter import ModelCompiler
from hydra.providers.base import ModelProvider
from hydra.registry.models import ModelProfile
from hydra.registry.registry import ModelRegistry
from hydra.scheduler.parallel import hedged

log = logging.getLogger("hydra.invoker")


def request_features(request: ModelRequest) -> dict:
    """Conditions under which a call ran (Failure Memory learns failure patterns from them)."""
    tokens = sum(len(str(m.get("content", ""))) for m in request.messages) // 4
    bucket = next((b for b in (4_000, 16_000, 32_000, 80_000) if tokens <= b), 1_000_000)
    return {
        "ctx_bucket": bucket,
        "structured": request.response_schema is not None,
        "tools": bool(request.tools),
        "images": any(m.get("images") for m in request.messages),
    }


class ModelInvoker:
    def __init__(
        self,
        providers: dict[str, ModelProvider],
        registry: ModelRegistry,
        hedge_after_ms: float = 3500,
        max_attempts: int = 3,
        compiler: ModelCompiler | None = None,
    ) -> None:
        self.providers = providers
        self.registry = registry
        self.hedge_after_ms = hedge_after_ms
        self.max_attempts = max_attempts
        self.compiler = compiler or ModelCompiler()

    async def _call_once(self, ctx: TaskContext, model: ModelProfile, request: ModelRequest,
                         role: str) -> ModelResponse:
        if not ctx.budget.can_call_model():
            raise BudgetExceeded("model call budget exhausted")
        provider = self.providers.get(model.provider)
        if provider is None:
            raise ModelError(f"no provider '{model.provider}'", ErrorKind.UNAVAILABLE)

        timeout = max(1.0, min(request.timeout_s, ctx.budget.remaining_s or 1.0))
        req = request.model_copy(update={"metadata": {**request.metadata, "role": role,
                                                      "runtime_options": dict(model.runtime_options)},
                                         "timeout_s": timeout})
        req = self.compiler.compile(model, req)
        await ctx.emit(EventType.MODEL_STARTED, role, {"model": model.id, "role": role})
        # Reserve with no await in between, so a hedged pair cannot both pass on one free unit.
        ctx.budget.reserve_model_call()
        try:
            try:
                resp = await asyncio.wait_for(provider.generate(model.physical_name, req), timeout=timeout + 1)
            except asyncio.TimeoutError as exc:
                raise ModelError(f"{model.id}: timeout", ErrorKind.TIMEOUT) from exc
            resp.model_id = model.id
            resp = self.compiler.decompile(req, resp)
        except BaseException:
            # Only successful calls count: a failed or cancelled (hedge loser) attempt returns its
            # unit, so FAST mode keeps its retry after a failure.
            ctx.budget.release_model_call()
            raise
        cost = model.estimate_cost(resp.input_tokens, resp.output_tokens)
        ctx.budget.charge_model(resp.input_tokens + resp.output_tokens, cost, reserved=True)
        self.registry.breaker.register_success(model.id, resp.latency_ms)
        return resp

    def _fallback(self, ctx: TaskContext, failed: ModelProfile, action: RetryAction) -> ModelProfile | None:
        route = ctx.route
        if action == RetryAction.SMALLER_MODEL and route is not None:
            if m := self.registry.smaller_than(failed, ctx.request, route):
                return m
        pool = [m for m in ctx.ranked if m.id not in ctx.failed_models and m.id != failed.id
                and self.registry.breaker.available(m.id)]
        if action == RetryAction.ALTERNATE_PROVIDER:
            other = [m for m in pool if m.provider != failed.provider]
            pool = other or pool
        return pool[0] if pool else None

    async def invoke(self, ctx: TaskContext, model: ModelProfile, request: ModelRequest,
                     role: str, hedge: bool = True) -> ModelResponse:
        current = model
        req = request
        last_error: BaseException | None = None

        for attempt in range(self.max_attempts):
            try:
                backup = self._fallback(ctx, current, RetryAction.HEDGE) if hedge else None
                use_hedge = backup is not None and ctx.budget.can_call_model(2)
                after_s = max(self.hedge_after_ms, current.estimated_latency_ms * 1.75) / 1000
                if use_hedge:
                    resp, winner = await hedged(
                        lambda: self._call_once(ctx, current, req, role),
                        lambda: self._call_once(ctx, backup, req, role),
                        after_s,
                    )
                    if winner == "backup":
                        await ctx.emit(EventType.RETRY_DECIDED, "invoker",
                                       {"action": "hedge_won", "from": current.id, "to": backup.id})
                else:
                    resp = await self._call_once(ctx, current, req, role)
                await self._completed(ctx, resp, role, request_features(req))
                return resp
            except BudgetExceeded:
                raise
            except Exception as exc:
                last_error = exc
                kind, action = decide(exc)
                self.registry.breaker.register_failure(current.id, fatal=kind == ErrorKind.OOM)
                ctx.failed_models.add(current.id)
                await ctx.emit(EventType.MODEL_FAILED, role,
                               {"model": current.id, "role": role, "kind": kind.value, "error": str(exc)[:500],
                                **request_features(req)})
                if action == RetryAction.FAIL or attempt == self.max_attempts - 1:
                    break

                if action == RetryAction.RETRY_STRUCTURED:
                    nxt = current
                    ctx.failed_models.discard(current.id)
                    req = req.model_copy(update={"temperature": 0.0, "messages": [
                        *req.messages,
                        {"role": "system", "content": "Return ONLY valid JSON matching the schema. No prose."},
                    ]})
                elif action == RetryAction.REPHRASE:
                    nxt = current
                    req = req.model_copy(update={"messages": [
                        {"role": "system", "content": "Answer helpfully and safely. If part of the request "
                                                      "cannot be done, do the rest and explain briefly."},
                        *req.messages,
                    ]})
                else:
                    nxt = self._fallback(ctx, current, action)
                await ctx.emit(EventType.RETRY_DECIDED, "invoker", {
                    "error_kind": kind.value, "action": action.value,
                    "from": current.id, "to": nxt.id if nxt else None,
                })
                if nxt is None:
                    break
                current = nxt
        assert last_error is not None
        raise last_error

    @staticmethod
    async def _completed(ctx: TaskContext, resp: ModelResponse, role: str, features: dict) -> None:
        await ctx.emit(EventType.MODEL_COMPLETED, role, {
            "model": resp.model_id, "role": role, "latency_ms": round(resp.latency_ms, 2),
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "tool_calls": len(resp.tool_calls), **features,
        })
