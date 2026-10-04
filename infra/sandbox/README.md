# HYDRA sandbox image

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Build locally:

    docker build -t hydra-sandbox:py312-v3 -f infra/sandbox/Dockerfile .

The CodeAgent expects this image by default. It contains Python 3.12, pytest, pytest-asyncio, ruff and mypy. Setting `HYDRA_SANDBOX_IMAGE` to this tag hardens the platform Docker sandbox too (both lines read that variable). Network remains disabled at runtime and the root filesystem is mounted read-only by HYDRA.

This tag is a development identity, not an immutable supply-chain pin. A future release gate will replace it with an image digest produced by CI.
