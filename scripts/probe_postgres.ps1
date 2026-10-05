# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param(
    [Parameter(Mandatory=$true)][string]$CredentialFile,
    [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference='Stop'
$taskConnection=Get-Content -LiteralPath $CredentialFile -Raw | ConvertFrom-Json
$taskSecure=ConvertTo-SecureString $taskConnection.password_dpapi
$taskPointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskSecure)
$taskPrevious=$env:HYDRA_POSTGRES_URL
try {
    $taskPassword=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskPointer)
    $taskUser=[Uri]::EscapeDataString($taskConnection.user)
    $taskEncoded=[Uri]::EscapeDataString($taskPassword)
    $env:HYDRA_POSTGRES_URL='postgresql://{0}:{1}@{2}:{3}/{4}' -f $taskUser,$taskEncoded,$taskConnection.host,$taskConnection.port,$taskConnection.database
    & $Python -m hydra.persistence.postgres_probe
    if ($LASTEXITCODE -ne 0) { throw 'Read-only PostgreSQL probe failed; no migration was attempted.' }
} finally {
    $env:HYDRA_POSTGRES_URL=$taskPrevious
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskPointer)
    Remove-Variable taskPassword,taskEncoded -ErrorAction SilentlyContinue
}
