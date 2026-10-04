# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA Python SDK (native protocol).

    from hydra.sdk import HydraClient
    c = HydraClient("http://127.0.0.1:8080", api_key="...")
    r = c.task("¿Cuánto es 17 × 23?", mode="fast")
    print(r["answer"], r["confidence"], r["learning"]["world_version"])
    for ev in c.stream("Explica HYDRA"): print(ev["type"])
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import httpx


class HydraError(RuntimeError):
    pass


class HydraClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080", api_key: str | None = None,
                 timeout: float = 600) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)

    def _req(self, method: str, path: str, **kw) -> Any:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise HydraError(f"{r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    # --- tasks / goals
    def task(self, goal: str, *, mode: str = "balanced", local_only: bool = False, **extra) -> dict:
        return self._req("POST", "/v1/tasks", json={"goal": goal, "mode": mode,
                                                    "constraints": {"local_only": local_only}, **extra})

    def goal(self, goal: str, *, workspace: str | None = None, mode: str = "balanced",
             authorized: list[str] | None = None) -> dict:
        return self._req("POST", "/hydra/v1/goals", json={"goal": goal, "workspace": workspace, "mode": mode,
                                                          "authorized": authorized or []})

    def stream(self, prompt: str, mode: str = "balanced") -> Iterator[dict]:
        body = {"messages": [{"role": "user", "content": prompt}], "mode": mode}
        with self.http.stream("POST", "/v1/hydra/stream", json=body) as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    yield json.loads(line[5:])

    # --- planes
    def world(self, query: str | None = None) -> dict:
        return self._req("POST", "/hydra/v1/world/query", json={"query": query}) if query else \
            self._req("GET", "/hydra/v1/world")

    def corpus_search(self, text: str, limit: int = 20) -> list[dict]:
        return self._req("POST", "/hydra/v1/corpus/query", json={"text": text, "limit": limit})

    def resolve(self, capability: str, **constraints) -> dict:
        return self._req("POST", "/hydra/v1/models/resolve", json={"capability": capability,
                                                                   "constraints": constraints})

    def translate(self, text: str, to: str, **kw) -> dict:
        return self._req("POST", "/v1/translate", json={"text": text, "target_language": to, **kw})

    def ledger_verify(self) -> dict:
        return self._req("GET", "/hydra/v1/ledger/verify")

    def invariants(self) -> list[dict]:
        return self._req("GET", "/hydra/v1/system/invariants")

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> HydraClient:
        return self

    def __exit__(self, *a) -> None:
        self.close()
