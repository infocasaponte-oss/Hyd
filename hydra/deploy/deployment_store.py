# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Persistence of the deployment registry (which variant serves which capability, and in which phase).

One node keeps it in ``deployments.json``. With a shared ``hydra.core.eventlog`` log (PostgreSQL
stream ``runtime/deployments.jsonl``) every change appends a full snapshot of the registry, and:

* ``mutate`` applies an admin operation on the latest snapshot while the stream is locked, so two
  nodes never overwrite each other's promotions or rollbacks;
* ``sync`` brings a node's in-memory registry (the one its traffic router reads) up to date with the
  changes made on other nodes;
* the first node that opens an empty stream adopts an existing ``deployments.json``.

Either way, when an operation fails half-way the in-memory registry is reloaded from what is stored,
instead of serving a state that was never persisted."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from hydra.deploy.deployment import Deployment, DeploymentState
from hydra.deploy.deployment_registry import DeploymentRegistry
from hydra.deploy.deployment_validation import DeploymentArtifactValidator
from hydra.model_factory.contracts import ModelVariant
from hydra.core.runtime_paths import runtime_path

log = logging.getLogger("hydra.runtime.deployments")
T = TypeVar("T")


class DeploymentStore:
    STREAM = "runtime/deployments.jsonl"

    def __init__(
        self,
        path: str | Path = runtime_path("deployments.json"),
        *,
        validator: DeploymentArtifactValidator | None = None,
        log=None,
    ):
        self.path = Path(path)
        self.validator = validator
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log  # None: the JSON file of a single node
        self._seen = 0
        if self.log is not None and len(self.log) == 0 and self.path.exists():
            self.log.append(json.dumps({"deployments": json.loads(self.path.read_text(encoding="utf-8"))},
                                       sort_keys=True))

    # ------------------------------------------------------------------ (de)serialisation
    @staticmethod
    def _body(registry: DeploymentRegistry) -> list[dict]:
        return [
            {
                "variant": item.variant.model_dump(mode="json"),
                "capabilities": sorted(item.capabilities),
                "state": item.state.value,
                "generation": item.generation,
                "metadata": item.metadata,
            }
            for item in registry.deployments.values()
        ]

    def _registry(self, body: list[dict], validate: bool | set[str] = True) -> DeploymentRegistry:
        """``validate``: True (every variant), False, or the set of variant ids to validate."""
        registry = DeploymentRegistry()
        for raw in body:
            variant = ModelVariant.model_validate(raw["variant"])
            metadata = raw.get("metadata", {})
            check = validate if isinstance(validate, bool) else str(variant.variant_id) in validate
            if self.validator is not None and check:
                self.validator.validate(
                    variant,
                    expected_fingerprint=metadata.get("gguf_fingerprint"),
                )
            registry.add(Deployment(
                variant=variant,
                capabilities=set(raw["capabilities"]),
                state=DeploymentState(raw["state"]),
                generation=raw["generation"],
                metadata=metadata,
            ))
        return registry

    def _latest(self) -> tuple[int, list[dict]]:
        if self.log is None:
            body = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            return 0, body
        seq = len(self.log)
        if seq == 0:
            return 0, []
        _, text = next(iter(self.log.read(seq - 1)))
        return seq, json.loads(text)["deployments"]

    @staticmethod
    def _replace(registry: DeploymentRegistry, fresh: DeploymentRegistry) -> None:
        registry.deployments.clear()
        registry.deployments.update(fresh.deployments)

    # ------------------------------------------------------------------ API
    def save(self, registry: DeploymentRegistry) -> None:
        body = self._body(registry)
        if self.log is not None:
            self._seen, _ = self.log.append(json.dumps({"deployments": body}, sort_keys=True))
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(body, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def load(self) -> DeploymentRegistry:
        self._seen, body = self._latest()
        return self._registry(body)

    def mutate(self, registry: DeploymentRegistry, change: Callable[[DeploymentRegistry], T]) -> T:
        """Apply ``change`` to the latest stored registry and persist the result; ``registry`` (the
        in-memory one the router reads) is updated in place. Exceptions from ``change`` propagate after
        ``registry`` is restored (to its state before the call on a single node, to the stored state of
        the cluster on a shared log)."""
        if self.log is None:
            before = self._body(registry)
            try:
                result = change(registry)
                self.save(registry)
            except BaseException:
                self._replace(registry, self._registry(before, validate=False))
                raise
            return result
        try:
            holder: dict[str, T] = {}

            def build(seq: int, last: str | None) -> str:
                if last is not None:  # the stream is locked: this is the latest state of the cluster
                    self._replace(registry, self._registry(json.loads(last)["deployments"], validate=False))
                holder["result"] = change(registry)
                return json.dumps({"deployments": self._body(registry)}, sort_keys=True)

            self._seen, _ = self.log.append(build)
            return holder["result"]
        except BaseException:
            self._seen, body = self._latest()
            self._replace(registry, self._registry(body, validate=False))
            raise

    def sync(self, registry: DeploymentRegistry) -> bool:
        """Adopt changes other nodes stored since this node last read or wrote. Variants new to this
        node are validated against their artifact first; if one fails, nothing is adopted (the node
        keeps routing on its current registry and retries on the next call)."""
        if self.log is None or len(self.log) == self._seen:
            return False
        seq, body = self._latest()
        known = set(registry.deployments)
        try:
            fresh = self._registry(body, validate={raw["variant"]["variant_id"] for raw in body} - known)
        except Exception:  # noqa: BLE001 - a missing or changed artifact on this node
            log.exception("deployment registry from the cluster not adopted on this node")
            return False
        self._replace(registry, fresh)
        self._seen = seq
        return True
