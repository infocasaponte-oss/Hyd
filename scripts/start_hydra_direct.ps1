# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
# Serves the v8 generalist on $Port; with -GroundedSpecialist also the v5 grounded specialist on $SpecialistPort.
param([int]$Port = 18090, [switch]$GroundedSpecialist, [int]$SpecialistPort = 18092)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$binary = Join-Path $root 'runtime/llama-cuda-b11146/llama-server.exe'
if (!(Test-Path -LiteralPath $binary)) { throw 'Missing pinned CUDA runtime b11146' }
$devices = (& $binary --list-devices 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $devices -notmatch 'CUDA') { throw "CUDA unavailable: $devices" }

# Every requested model is verified before any server starts, so a bad file never leaves one half running.
$servers = @(@{ Relative = 'models/hydra-instruction-v8/HYDRA.gguf'; Sha256 = '0ef14148ababf98c52623f164d776ed76f17a583175ea91301e024a157231761'; Alias = 'hydra-instruction-v8'; Port = $Port; Context = 2048; Log = 'hydra-direct' })
if ($GroundedSpecialist) {
    $servers += @{ Relative = 'models/hydra-program-v5-grounded/HYDRA.gguf'; Sha256 = '3442f057df020309dd80431c797fda7390135d14be575be5a328275077e6c987'; Alias = 'hydra-program-v5-grounded'; Port = $SpecialistPort; Context = 4096; Log = 'hydra-grounded' }
}
foreach ($s in $servers) {
    $model = Join-Path $root $s.Relative
    if (!(Test-Path -LiteralPath $model)) { throw "Missing GGUF: $($s.Relative)" }
    if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash.ToLower() -ne $s.Sha256) { throw "GGUF hash mismatch: $($s.Relative)" }
    if (Get-NetTCPConnection -State Listen -LocalPort $s.Port -ErrorAction SilentlyContinue) { throw "Port $($s.Port) already in use" }
}
foreach ($s in $servers) {
    Start-Process -FilePath $binary -WorkingDirectory $root -WindowStyle Hidden -ArgumentList @('--model', (Join-Path $root $s.Relative), '--alias', $s.Alias, '--host', '127.0.0.1', '--port', "$($s.Port)", '--ctx-size', "$($s.Context)", '--n-gpu-layers', '99', '--parallel', '1', '--jinja') -RedirectStandardOutput (Join-Path $root "runtime/$($s.Log).stdout.log") -RedirectStandardError (Join-Path $root "runtime/$($s.Log).stderr.log") -PassThru
}
