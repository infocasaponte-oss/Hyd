# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param([int]$Port = 8009)
$ErrorActionPreference = 'Stop'
$hydRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $hydRoot
$hydPython = Join-Path $hydRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $hydPython)) { throw 'Missing HYDRA Python environment.' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already occupied. Hyd will not interrupt an existing service."
}
& $hydPython -m hydra.hyd.serve --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Hyd startup failed.' }
