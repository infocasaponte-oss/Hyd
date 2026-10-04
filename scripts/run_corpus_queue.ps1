# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$CalibratorRoot
)
$ErrorActionPreference = 'Stop'
$queuePath = (Resolve-Path -LiteralPath $Root).Path
$codePath = (Resolve-Path -LiteralPath $CalibratorRoot).Path
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$lockPath = Join-Path $queuePath 'worker.lock'
$stopPath = Join-Path $queuePath 'stop-worker'
$logPath = Join-Path $queuePath 'worker.log'
$pidPath = Join-Path $queuePath 'worker.pid'
$lockHandle = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
try {
    Set-Location -LiteralPath $codePath
    $PID | Set-Content -LiteralPath $pidPath
    "started $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath
    while (-not (Test-Path -LiteralPath $stopPath)) {
        $result = & $pythonPath -m hyd_calibrator run-download-queue --root $queuePath --max-jobs 10 2>&1
        if ($LASTEXITCODE -ne 0) {
            "failed $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath
            $result | Add-Content -LiteralPath $logPath
            break
        }
        $parsed = ($result -join "`n") | ConvertFrom-Json
        if ($parsed.jobs.Count -gt 0) {
            "processed $($parsed.jobs.Count) $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath
        }
        Start-Sleep -Seconds 10
    }
    "stopped $(Get-Date -Format o)" | Add-Content -LiteralPath $logPath
} finally {
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
    $lockHandle.Dispose()
}
