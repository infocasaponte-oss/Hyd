# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param([int]$DownloadTimeoutSeconds = 14400)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force runtime | Out-Null
$statusPath = Join-Path $PWD 'runtime/build-local-status.json'
$lockPath = Join-Path $PWD 'runtime/build-local.lock'
# Keep the lock open: a concurrent invocation must not write to the same partial weights.
$lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
$transcriptStarted = $false
function Save-BuildStatus([string]$Stage, [string]$ErrorMessage = '') {
    @{ stage = $Stage; updated_at = [DateTime]::UtcNow.ToString('o'); pid = $PID;
       approved = $false; error = $ErrorMessage } | ConvertTo-Json |
        Set-Content -LiteralPath "$statusPath.tmp" -Encoding utf8
    Move-Item -LiteralPath "$statusPath.tmp" -Destination $statusPath -Force
}
try {
    Start-Transcript -Path runtime/build-local.log -Append | Out-Null
    $transcriptStarted = $true
    Save-BuildStatus 'PREPARING'
    & "$PSScriptRoot/prepare_hydra.ps1" -DownloadTimeoutSeconds $DownloadTimeoutSeconds
    $python = Join-Path $PWD '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath data/hydra-corpus-v1/manifest.json)) {
        Save-BuildStatus 'CREATING_CORPUS'
        & $python -m hydra.training.verified_corpus
        if ($LASTEXITCODE -ne 0) { throw 'Corpus creation failed.' }
    }
    Save-BuildStatus 'PREFLIGHT'
    & $python -m hydra.model_factory.build_hydra --check
    if ($LASTEXITCODE -ne 0) { throw 'Build preflight failed.' }
    Save-BuildStatus 'BUILDING'
    & $python -m hydra.model_factory.build_hydra
    if ($LASTEXITCODE -ne 0) { throw 'Training or GGUF conversion failed; inspect models/hydra-pilot logs.' }
    Save-BuildStatus 'CANDIDATE_REQUIRES_EVALUATION'
} catch {
    Save-BuildStatus 'FAILED' $_.Exception.Message
    throw
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    $lock.Dispose()
}
