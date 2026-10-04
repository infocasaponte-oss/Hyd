# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param([int]$DownloadTimeoutSeconds = 3600)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$recipe = Get-Content config/recipes/hydra-pilot.json -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force models/base,runtime | Out-Null
function Download-Resumable([string]$Url, [string]$Target, [string]$ExpectedSha256 = '', [long]$ExpectedBytes = 0) {
    if (Test-Path -LiteralPath $Target) {
        if ($ExpectedSha256 -and (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256) {
            throw "Existing file checksum mismatch: $Target. Preserve it for diagnosis and supply the pinned artifact."
        }
        return
    }
    $partial = "$Target.partial"
    $length = if (Test-Path -LiteralPath $partial) { (Get-Item -LiteralPath $partial).Length } else { 0 }
    if ($ExpectedBytes -gt 0 -and $length -gt $ExpectedBytes) { throw "Partial file exceeds expected size: $partial" }
    if ($ExpectedBytes -eq 0 -or $length -ne $ExpectedBytes) {
        curl.exe --fail --location --continue-at - --connect-timeout 30 --speed-limit 1024 --speed-time 60 --retry 2 --max-time $DownloadTimeoutSeconds --output $partial $Url
        if ($LASTEXITCODE -ne 0) { throw "Download incomplete: $partial. Run this script again to resume." }
    }
    if ($ExpectedBytes -gt 0 -and (Get-Item -LiteralPath $partial).Length -ne $ExpectedBytes) { throw "Downloaded size mismatch: $partial" }
    if ($ExpectedSha256 -and (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256) {
        throw "Downloaded checksum mismatch: $partial. The file was not promoted to training input."
    }
    Move-Item -LiteralPath $partial -Destination $Target
}
foreach ($file in @('LICENSE','README.md','config.json','generation_config.json','merges.txt','tokenizer.json','tokenizer_config.json','vocab.json')) {
    Download-Resumable "https://huggingface.co/$($recipe.base_repository)/resolve/$($recipe.base_revision)/$file" "models/base/$file"
}
Download-Resumable "https://huggingface.co/$($recipe.base_repository)/resolve/$($recipe.base_revision)/model.safetensors?download=true" 'models/base/model.safetensors' $recipe.base_sha256 $recipe.base_size_bytes
$actual = (Get-FileHash models/base/model.safetensors -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $recipe.base_sha256) { throw 'Base model checksum mismatch. Do not train this file.' }
$tag = $recipe.llamacpp_revision
Download-Resumable "https://github.com/ggml-org/llama.cpp/archive/refs/tags/$tag.zip" 'runtime/llama-source.zip'
if (-not (Test-Path runtime/llama.cpp/convert_hf_to_gguf.py)) {
    Expand-Archive -LiteralPath runtime/llama-source.zip -DestinationPath runtime/source -Force
    # Copy from the fixed extracted directory; preserve any existing installation.
    Copy-Item -LiteralPath "runtime/source/llama.cpp-$tag" -Destination runtime/llama.cpp -Recurse
}
Download-Resumable "https://github.com/ggml-org/llama.cpp/releases/download/$tag/llama-$tag-bin-win-cpu-x64.zip" 'runtime/llama-cpu.zip'
if (-not (Test-Path -LiteralPath $recipe.quantizer)) {
    Expand-Archive -LiteralPath runtime/llama-cpu.zip -DestinationPath runtime/llama-bin -Force
}
if (-not (Test-Path .venv/Scripts/python.exe)) {
    py -3.12 -m venv --system-site-packages .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create training environment.' }
}
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r scripts/requirements-training.txt
if ($LASTEXITCODE -ne 0) { throw 'Training dependencies failed.' }
.\.venv\Scripts\python.exe -m pip install -e runtime/llama.cpp/gguf-py
if ($LASTEXITCODE -ne 0) { throw 'GGUF conversion dependencies failed.' }
Write-Host 'Prepared. Run: .\.venv\Scripts\python.exe -m hydra.model_factory.build_hydra --check'
