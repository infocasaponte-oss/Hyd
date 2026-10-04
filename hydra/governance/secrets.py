# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Secrets Broker: models never see real secrets.

    LLM: call github.read_repo(repo="x")
    broker: tool identity -> credential policy -> secret reference -> temporary credential -> execution
    the RESULT goes back to the model, never the key.

References look like ``secret://github/token``. Values come from an encrypted local store
(Fernet), environment variables (``HYDRA_SECRET_GITHUB_TOKEN``) or an external vault
adapter. Every resolution is audited and any echo of a secret is redacted."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from hydra.core.atomic import write_bytes_atomic, write_text_atomic

REF = re.compile(r"secret://([\w.-]+)/([\w.-]+)")


class CredentialPolicy(BaseModel):
    ref: str
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_principals: list[str] = Field(default_factory=lambda: ["*"])
    max_uses_per_task: int = 100


class SecretsBroker:
    def __init__(self, root: Path, audit: Callable[[str, dict], Any] | None = None, keystore=None,
                 docs=None) -> None:
        from cryptography.fernet import Fernet

        from hydra.core.keystore import KeyStore

        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        store = keystore or KeyStore(root.parent, backend="legacy")
        self.fernet = Fernet(store.get_or_create("secrets-broker", root / ".broker.key", Fernet.generate_key))
        self.store = root / "secrets.enc"
        self.audit = audit
        self._uses: dict[tuple[str, str], int] = {}
        # Shared (PostgreSQL documents): the encrypted vault is one document holding the Fernet token
        # (never the plaintext) and policies another; on files, secrets.enc and policies.json as before.
        self._docs = docs if docs is not None and docs.backend == "postgres" else None
        self._vault = self._policies = None
        if self._docs is not None:
            self._vault = self._docs.document("secrets/vault", self.root / "secrets.vault.json",
                                              default=lambda: {"token": None})
            if self._vault.get().get("token") is None and self.store.exists():
                token = self.store.read_bytes().decode("ascii")
                self._vault.update(lambda d: d if d.get("token") else {"token": token})
            self._policies = self._docs.document("secrets/policies", self.root / "policies.json", default=list)

    @property
    def policies(self) -> dict[str, CredentialPolicy]:
        if self._policies is not None:
            raw = self._policies.get()
        else:
            pol = self.root / "policies.json"
            raw = json.loads(pol.read_text()) if pol.exists() else []
        return {p["ref"]: CredentialPolicy(**p) for p in raw}

    def _load(self) -> dict[str, str]:
        if self._vault is not None:
            token = self._vault.get().get("token")
            return json.loads(self.fernet.decrypt(token.encode("ascii"))) if token else {}
        if not self.store.exists():
            return {}
        return json.loads(self.fernet.decrypt(self.store.read_bytes()))

    def put(self, ref: str, value: str, policy: CredentialPolicy | None = None) -> None:
        if self._vault is not None:
            def add(d: dict) -> dict:
                data = json.loads(self.fernet.decrypt(d["token"].encode("ascii"))) if d.get("token") else {}
                data[ref] = value
                return {"token": self.fernet.encrypt(json.dumps(data).encode()).decode("ascii")}

            self._vault.update(add)
            if policy:
                self._policies.update(lambda rows: [p for p in rows if p["ref"] != ref] + [policy.model_dump()])
            return
        data = self._load()
        data[ref] = value
        write_bytes_atomic(self.store, self.fernet.encrypt(json.dumps(data).encode()))
        if policy:
            policies = {**self.policies, ref: policy}
            write_text_atomic(self.root / "policies.json", json.dumps([p.model_dump() for p in policies.values()]))

    def refs(self) -> list[str]:
        env = [f"secret://{k[13:].lower().replace('_', '/', 1)}" for k in os.environ if k.startswith("HYDRA_SECRET_")]
        return sorted(set(self._load()) | set(env))

    def _value(self, ref: str) -> str | None:
        v = self._load().get(ref)
        if v is None:
            m = REF.fullmatch(ref)
            if m:
                v = os.environ.get(f"HYDRA_SECRET_{m.group(1)}_{m.group(2)}".upper().replace("-", "_").replace(".", "_"))
        return v

    def resolve(self, ref: str, *, tool: str, principal: str = "hydra", task_id: str = "") -> str:
        pol = self.policies.get(ref)
        if pol is not None:
            if pol.allowed_tools and tool not in pol.allowed_tools:
                raise PermissionError(f"tool {tool} may not use {ref}")
            if "*" not in pol.allowed_principals and principal not in pol.allowed_principals:
                raise PermissionError(f"principal {principal} may not use {ref}")
            n = self._uses.get((ref, task_id), 0) + 1
            if n > pol.max_uses_per_task:
                raise PermissionError(f"{ref} used too many times in task {task_id}")
            self._uses[(ref, task_id)] = n
        value = self._value(ref)
        if value is None:
            raise KeyError(f"unknown secret {ref}")
        if self.audit:
            self.audit("SECRET_RESOLVED", {"ref": ref, "tool": tool, "principal": principal, "task": task_id})
        return value

    def inject(self, arguments: Any, *, tool: str, principal: str = "hydra", task_id: str = "") -> Any:
        """Replace secret:// references inside tool arguments right before execution."""
        if isinstance(arguments, str):
            return REF.sub(lambda m: self.resolve(m.group(0), tool=tool, principal=principal, task_id=task_id),
                           arguments)
        if isinstance(arguments, dict):
            return {k: self.inject(v, tool=tool, principal=principal, task_id=task_id) for k, v in arguments.items()}
        if isinstance(arguments, list):
            return [self.inject(v, tool=tool, principal=principal, task_id=task_id) for v in arguments]
        return arguments

    def redact(self, value: Any) -> Any:
        """Remove any known secret value from outputs before they reach a model or a log."""
        secrets = [v for v in self._load().values() if len(v) >= 6]
        secrets += [v for k, v in os.environ.items() if k.startswith("HYDRA_SECRET_") and len(v) >= 6]
        if isinstance(value, str):
            for s in secrets:
                value = value.replace(s, "[REDACTED-SECRET]")
            return value
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value
