#!/usr/bin/env bash
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
# Start llama-server with the profile chosen by the AutoBuilder (.env) and HYDRA's gateway on top.
set -euo pipefail
set -a; [ -f .env ] && . ./.env; set +a
BIN="${HYDRA_LLAMACPP_DIR:-runtime/llama.cpp}/build/bin/llama-server"
"$BIN" -m "${HYDRA_MODEL:?set HYDRA_MODEL}" -ngl "${HYDRA_GPU_LAYERS:-99}" -c "${HYDRA_CONTEXT:-8192}" \
  -np "${HYDRA_PARALLEL:-1}" -ctk "${HYDRA_KV_K:-q8_0}" -ctv "${HYDRA_KV_V:-q8_0}" -fa on \
  --host 127.0.0.1 --port 8081 &
exec python -m hydra.cli serve --host 0.0.0.0 --port 8080
