#!/usr/bin/env bash
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
set -euo pipefail

HOST="${HYDRA_API_HOST:-127.0.0.1}"
PORT="${HYDRA_API_PORT:-8080}"

if [[ "$HOST" != "127.0.0.1" && "$HOST" != "localhost" ]]; then
  if [[ -z "${HYDRA_API_KEY:-}${HYDRA_API_TOKEN:-}" ]]; then
    echo "Refusing non-local bind without HYDRA_API_KEY (or HYDRA_API_TOKEN)." >&2
    exit 2
  fi
fi

# Unified gateway: platform routes + HYDRA-SO runtime line (/ready, /hydra/v1/admin/*, ...).
exec hydra serve --host "$HOST" --port "$PORT"
