# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param([string]$Model = 'models/hydra-pilot/HYDRA.gguf', [int]$Port = 8080)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$resolvedModel = (Resolve-Path -LiteralPath $Model).Path
$manifestPath = Join-Path (Split-Path $resolvedModel -Parent) 'build-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Missing build-manifest.json: build the candidate first.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.status -ne 'CANDIDATE_REQUIRES_EVALUATION') { throw 'Build is not a completed candidate.' }
$digest = (Get-FileHash -LiteralPath $resolvedModel -Algorithm SHA256).Hash.ToLowerInvariant()
if ($digest -ne $manifest.sha256) { throw 'Model hash does not match build manifest.' }
New-Item -ItemType Directory -Force runtime | Out-Null
@"
FROM "$resolvedModel"
PARAMETER num_ctx 2048
PARAMETER temperature 0
"@ | Set-Content -LiteralPath runtime/HYDRA.Modelfile -Encoding utf8
ollama create hydra-local -f runtime/HYDRA.Modelfile
if ($LASTEXITCODE -ne 0) { throw 'Ollama model import failed.' }
$served = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/show' -Method Post -ContentType 'application/json' -Body '{"model":"hydra-local"}'
if ($served.modelfile -notmatch '(?m)^FROM\s+"?[^\r\n"]*sha256[-:]([0-9a-f]{64})"?\s*$' -or $Matches[1] -ne $digest) {
    throw 'Ollama is not serving the candidate GGUF hash.'
}
$env:HYDRA_MODELS_CONFIG = 'config/models.hydra.yaml'
$env:HYDRA_OFFLINE = 'false'
$env:HYDRA_BUDGET_TIME_SCALE = '6'
$env:HYDRA_SANDBOX_BACKEND = 'docker'
py -3.12 -m hydra.cli serve --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw 'HYDRA gateway failed.' }
