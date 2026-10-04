# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param([int]$DownloadTimeoutSeconds = 14400)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path $PWD 'runtime/kev-env/Scripts/python.exe'
$wheel = Join-Path $PWD 'runtime/wheels/torch-2.8.0+cu128-cp312-cp312-win_amd64.whl'
$expected = '0ad925202387f4e7314302a1b4f8860fa824357f9b1466d7992bf276370ebcff'
$size = 3461384651L
$statusPath = Join-Path $PWD 'runtime/kev-cuda-status.json'
New-Item -ItemType Directory -Force runtime/wheels | Out-Null
$lock = [IO.File]::Open((Join-Path $PWD 'runtime/kev-cuda.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
function Save-CudaStatus([string]$Stage, [string]$Detail = '') {
    @{stage=$Stage; detail=$Detail; pid=$PID; updated_at=[DateTime]::UtcNow.ToString('o')} |
        ConvertTo-Json | Set-Content "$statusPath.tmp" -Encoding utf8
    Move-Item -LiteralPath "$statusPath.tmp" -Destination $statusPath -Force
}
try {
    if (-not (Test-Path -LiteralPath $python)) { throw 'Missing isolated Kev environment.' }
    Save-CudaStatus 'DOWNLOADING'
    if (-not (Test-Path -LiteralPath $wheel)) {
        $partial = "$wheel.partial"
        $length = if (Test-Path -LiteralPath $partial) { (Get-Item -LiteralPath $partial).Length } else { 0 }
        if ($length -gt $size) { throw 'CUDA partial exceeds pinned wheel size.' }
        if ($length -lt $size) {
            curl.exe --fail --location --continue-at - --connect-timeout 30 --speed-limit 1024 --speed-time 90 --retry 2 --max-time $DownloadTimeoutSeconds --output $partial 'https://download.pytorch.org/whl/cu128/torch-2.8.0%2Bcu128-cp312-cp312-win_amd64.whl'
            if ($LASTEXITCODE -ne 0) { throw 'CUDA download incomplete; rerun to resume.' }
        }
        if ((Get-Item -LiteralPath $partial).Length -ne $size -or (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            throw 'CUDA wheel verification failed.'
        }
        Move-Item -LiteralPath $partial -Destination $wheel
    }
    if ((Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'CUDA wheel hash mismatch.' }
    Save-CudaStatus 'INSTALLING'
    & $python -m pip install --upgrade --no-deps $wheel
    if ($LASTEXITCODE -ne 0) { throw 'CUDA wheel installation failed.' }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Kev dependencies inconsistent.' }
    Save-CudaStatus 'VERIFYING_GPU'
    & $python -c "import json,torch; from pathlib import Path; assert torch.cuda.is_available(), 'CUDA unavailable'; x=torch.ones(16,device='cuda'); torch.cuda.synchronize(); r={'torch':torch.__version__,'cuda':torch.version.cuda,'device':torch.cuda.get_device_name(0),'sum':x.sum().item()}; assert r['sum']==16; Path('runtime/kev-cuda-evidence.json').write_text(json.dumps(r,indent=2)); print(r)"
    if ($LASTEXITCODE -ne 0) { throw 'CUDA execution smoke failed.' }
    & $python -m pip freeze | Set-Content runtime/kev-environment.txt -Encoding utf8
    Save-CudaStatus 'CUDA_VERIFIED' 'Tensor executed on GPU; Kev model inference still requires its own validation.'
} catch {
    Save-CudaStatus 'FAILED' $_.Exception.Message
    throw
} finally {
    $lock.Dispose()
}
