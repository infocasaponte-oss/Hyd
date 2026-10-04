# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from hydra.deploy.deployment_registry import DeploymentRegistry

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class PhysicalInferenceUnavailable(LookupError):
    pass


@dataclass
class PhysicalInferenceClient:
    registry: DeploymentRegistry
    transport: httpx.AsyncBaseTransport | None = None

    def _deployment(self, variant_id: str):
        deployment = self.registry.deployments.get(variant_id)
        if deployment is None:
            raise PhysicalInferenceUnavailable("Physical deployment not found")
        return deployment

    @staticmethod
    def _endpoint(deployment) -> str:
        endpoint = deployment.variant.metadata.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise PhysicalInferenceUnavailable("Deployment endpoint is not configured")
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in _LOCAL_HOSTS:
            raise PhysicalInferenceUnavailable(
                "Physical inference endpoint must be local HTTP"
            )
        return endpoint.rstrip("/")

    async def generate(
        self,
        variant_id: str,
        prompt: str,
        max_tokens: int,
    ) -> str:
        deployment = self._deployment(variant_id)
        endpoint = self._endpoint(deployment)
        model = deployment.variant.metadata.get(
            "served_model",
            deployment.variant.lineage.base_model,
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=120.0,
            ) as client:
                response = await client.post(
                    f"{endpoint}/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise PhysicalInferenceUnavailable(
                "Physical inference endpoint is unavailable"
            ) from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PhysicalInferenceUnavailable(
                "Physical inference response is invalid"
            ) from exc
