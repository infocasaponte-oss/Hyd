#!/usr/bin/env bash
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
# HYDRA workstation bootstrap (Linux): detect GPU -> build llama.cpp for its CUDA arch -> install HYDRA.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || { echo "No NVIDIA GPU found"; exit 1; }
python3 -m venv .venv && . .venv/bin/activate
pip install -U pip && pip install -e ".[all,dev]"
ARCH=$(python -c "from hydra.edge.profiles import detect_profile; print(detect_profile().cuda_arch or '')")
echo "CUDA architecture: ${ARCH:-none}"
mkdir -p runtime
[ -d runtime/llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp runtime/llama.cpp
cmake -S runtime/llama.cpp -B runtime/llama.cpp/build ${ARCH:+-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=$ARCH} -DCMAKE_BUILD_TYPE=Release
cmake --build runtime/llama.cpp/build --config Release -j
ls runtime/llama.cpp/build/bin/llama-server runtime/llama.cpp/build/bin/llama-quantize
python -m hydra.cli edge profile > runtime/hardware.json
echo "HYDRA_LLAMACPP_DIR=$ROOT/runtime/llama.cpp" >> .env
echo "OK. Next: ./scripts/autobuild.sh <model.gguf|ollama-tag>"
