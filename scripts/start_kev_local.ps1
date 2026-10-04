# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param([int]$Port = 8009, [switch]$CpuOnly)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$source = Join-Path $PWD 'runtime/kev'
$python = Join-Path $PWD 'runtime/kev-env/Scripts/python.exe'
$revision = '0c142becde423a0c68ec857f7831dac0315588a1'
$model = 'jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e'
if (-not (Test-Path -LiteralPath "$source/.git")) { throw 'Missing isolated Kev checkout in runtime/kev.' }
$actual = git -C $source rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actual -ne $revision) { throw 'Kev checkout does not match the reviewed revision.' }
if (git -C $source status --porcelain --untracked-files=no) { throw 'Kev tracked source has local changes.' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Create the isolated runtime/kev-env environment first.' }
# Dedicated cache keeps Kev assets separate from the generative HYDRA environment.
$env:HF_HOME = Join-Path $PWD 'runtime/kev-cache'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:HF_HUB_DISABLE_XET = '1'
if ($CpuOnly) {
    $env:CUDA_VISIBLE_DEVICES = '-1'
    $env:KEV_DTYPE = 'fp32'
} else {
    & $python -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable: install CUDA PyTorch in runtime/kev-env'; print(torch.cuda.get_device_name(0))"
    if ($LASTEXITCODE -ne 0) { throw 'GPU preflight failed. CPU requires explicit -CpuOnly.' }
    $env:KEV_DTYPE = 'bf16'
}
& $python -m kev.serve --run $model --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Kev startup failed; do not enable decision routing.' }
