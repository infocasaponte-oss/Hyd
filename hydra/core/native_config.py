# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Runtime-line settings: a frozen view of the platform ``hydra.core.config.Settings``.

One source of configuration for the whole gateway: the same ``HYDRA_*`` variables, read once by the
platform Settings (process environment first, then ``./.env``). ``HYDRA_API_TOKEN`` stays accepted
as an alias of ``HYDRA_API_KEY``."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydra.core.environment import _DOTENV, _env

__all__ = ["Settings", "_DOTENV", "_env"]

@dataclass(frozen=True)
class Settings:
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    llm_url: str = "http://127.0.0.1:8081/v1"
    models_dir: str = "models"
    repositories_root: str = "repositories"
    runtime_dir: str = "runtime"
    runtime_db: str = str(Path("runtime") / "hydra.db")
    deployments_file: str = str(Path("runtime") / "deployments.json")
    readiness_max_pending: int = 1000
    readiness_max_pending_age_seconds: float = 300.0
    api_token: str | None = None
    admin_token: str | None = None
    client_keys_file: str = "data/keys/api-clients.json"
    api_rate_limit_per_minute: int = 60
    admin_rate_limit_per_minute: int = 6
    sandbox_image: str = "hydra-sandbox:py312-v3"
    sandbox_runtime: str = "docker"
    code_verification_mode: str = "advisory"
    workspace_max_files: int = 20000
    workspace_max_bytes: int = 256 * 1024 * 1024
    max_input_chars: int = 50000
    max_output_tokens: int = 4096
    max_translation_chunks: int = 64
    runtime_backend: str = "file"
    postgres_url: str = ""
    data_dir: str = "data"
    artifact_objects: str = ""
    s3_endpoint_url: str = ""
    otel_endpoint: str = ""

    @classmethod
    def from_platform(cls, platform=None) -> Settings:
        """Build the view from a platform Settings (default: read the environment now)."""
        if platform is None:
            from hydra.core.config import Settings as PlatformSettings

            platform = PlatformSettings()
        p = platform
        runtime_dir = p.runtime_dir
        return cls(
            api_host=p.api_host, api_port=p.api_port, llm_url=p.llm_url, models_dir=p.models_dir,
            repositories_root=str(p.repositories_root), runtime_dir=runtime_dir,
            runtime_db=p.runtime_db or str(Path(runtime_dir) / "hydra.db"),
            deployments_file=p.deployments_file or str(Path(runtime_dir) / "deployments.json"),
            readiness_max_pending=p.readiness_max_pending,
            readiness_max_pending_age_seconds=p.readiness_max_pending_age_seconds,
            api_token=p.api_key or None, admin_token=p.admin_token or None,
            client_keys_file=str(p.client_keys_file),
            api_rate_limit_per_minute=p.api_rate_limit_per_minute,
            admin_rate_limit_per_minute=p.admin_rate_limit_per_minute,
            sandbox_image=p.sandbox_image, sandbox_runtime=p.sandbox_runtime,
            code_verification_mode=p.code_verification_mode, workspace_max_files=p.workspace_max_files,
            workspace_max_bytes=p.workspace_max_bytes, max_input_chars=p.max_input_chars,
            max_output_tokens=p.max_output_tokens, max_translation_chunks=p.max_translation_chunks,
            runtime_backend=p.runtime_backend, postgres_url=p.postgres_url, data_dir=str(p.data_dir),
            artifact_objects=p.artifact_objects, s3_endpoint_url=p.s3_endpoint_url, otel_endpoint=p.otel_endpoint)


settings = Settings.from_platform()
