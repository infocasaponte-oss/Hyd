#!/usr/bin/env bash
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
# HF/safetensors -> GGUF BF16 -> importance matrix (optional) -> llama-quantize (via the Model Factory DAG).
set -euo pipefail
SRC="${1:?model dir or hf:org/name}"; NAME="${2:-hydra-main}"; QUANT="${3:-Q4_K_M}"
python -m hydra.cli model import "$SRC" --name "$NAME"
python -m hydra.cli model build "$NAME" --quant "$QUANT"
python -m hydra.cli model list
