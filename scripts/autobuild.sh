#!/usr/bin/env bash
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
# AutoBuilder: benchmark runtime candidates on this machine and apply the winner to .env.
set -euo pipefail
MODEL="${1:-${HYDRA_MODEL:?give a .gguf path or an Ollama tag}}"
RUNTIME="ollama"; [[ "$MODEL" == *.gguf ]] && RUNTIME="llama.cpp"
python -m hydra.cli build --auto --model "$MODEL" --runtime "$RUNTIME" \
  --llama-server "${HYDRA_LLAMACPP_DIR:-runtime/llama.cpp}/build/bin/llama-server" --apply
