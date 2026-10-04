# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
# HYDRA workstation bootstrap (Windows): venv + HYDRA + llama.cpp built for the local CUDA arch.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
py -3.12 -m venv .venv; .\.venv\Scripts\python -m pip install -U pip; .\.venv\Scripts\pip install -e ".[all,dev]"
$arch = .\.venv\Scripts\python -c "from hydra.edge.profiles import detect_profile; print(detect_profile().cuda_arch or '')"
Write-Host "CUDA architecture: $arch"
New-Item -ItemType Directory -Force runtime | Out-Null
if (-not (Test-Path runtime\llama.cpp)) { git clone --depth 1 https://github.com/ggml-org/llama.cpp runtime\llama.cpp }
$flags = @("-DCMAKE_BUILD_TYPE=Release"); if ($arch) { $flags += @("-DGGML_CUDA=ON", "-DCMAKE_CUDA_ARCHITECTURES=$arch") }
cmake -S runtime\llama.cpp -B runtime\llama.cpp\build @flags
cmake --build runtime\llama.cpp\build --config Release -j
Add-Content .env "HYDRA_LLAMACPP_DIR=$((Resolve-Path runtime\llama.cpp).Path)"
Write-Host "OK. Next: .\.venv\Scripts\hydra build --auto --model qwen3:8b --apply"
