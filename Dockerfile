# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
FROM docker:29-cli AS dockercli

# Same interpreter as CI, pyproject (target py312) and the sandbox image.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="HYDRA Cognitive Engine" \
      org.opencontainers.image.authors="Luis Manuel Cousido Hermida" \
      org.opencontainers.image.licenses="LicenseRef-Proprietary" \
      org.opencontainers.image.description="Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved."

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HYDRA_WORKSPACE_DIR=/workspace HYDRA_DATA_DIR=/data

# Docker CLI only (no daemon): the sandbox talks to the restricted socket proxy.
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY hydra ./hydra
# config/ and sql/ go in before the install: pyproject data-files ships config/*.yaml and
# sql/schema.sql in the wheel (installed console scripts resolve them under share/hydra).
COPY config ./config
COPY sql ./sql
RUN pip install --no-cache-dir ".[all]"

# uvicorn imports hydra from /app (its app-dir), so the runtime subsystem keeps its state in /app/runtime.
RUN useradd --create-home --uid 10001 hydra && mkdir -p /workspace /data /keys /app/runtime \
    && chown hydra /workspace /data /keys /app/runtime && chmod 700 /keys
USER hydra

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"
CMD ["uvicorn", "hydra.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
