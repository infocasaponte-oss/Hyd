# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param([switch]$Foreground, [string]$Plan, [switch]$AuthorizePretraining)
$ErrorActionPreference = 'Stop'
$hydRoot = Split-Path $PSScriptRoot -Parent
$hydPython = Join-Path $hydRoot '.venv/Scripts/python.exe'
$hydState = Join-Path $hydRoot 'runtime/hyd-stage1'
$hydStatus = Join-Path $hydState 'status.json'
if (Test-Path -LiteralPath $hydStatus) {
    $hydExisting = Get-Content -LiteralPath $hydStatus -Raw | ConvertFrom-Json
    $hydProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($hydExisting.pid)" -ErrorAction SilentlyContinue
    if ($hydProcess.CommandLine -match 'hydra\.hyd\.stage1') { throw 'Hyd stage-1 pipeline is already running.' }
}
New-Item -ItemType Directory -Force -Path $hydState | Out-Null
$hydArguments = @('-m', 'hydra.hyd.stage1', '--wait')
if ($AuthorizePretraining) { $hydArguments += '--authorize-pretraining' }
if ($Plan) {
    $hydPlanPath = (Resolve-Path -LiteralPath $Plan).Path
    $hydArguments += @('--plan', ('"' + $hydPlanPath + '"'))
}
if ($Foreground) {
    Set-Location -LiteralPath $hydRoot
    $hydForegroundArgs = @('-m', 'hydra.hyd.stage1', '--wait')
    if ($Plan) { $hydForegroundArgs += @('--plan', $hydPlanPath) }
    if ($AuthorizePretraining) { $hydForegroundArgs += '--authorize-pretraining' }
    & $hydPython @hydForegroundArgs
    if ($LASTEXITCODE -ne 0) { throw 'Hyd stage-1 pipeline failed; inspect runtime/hyd-stage1/status.json.' }
} else {
    Start-Process -FilePath $hydPython -WorkingDirectory $hydRoot -WindowStyle Hidden -ArgumentList $hydArguments -RedirectStandardOutput (Join-Path $hydState 'stdout.log') -RedirectStandardError (Join-Path $hydState 'stderr.log') -PassThru | Select-Object Id
}
