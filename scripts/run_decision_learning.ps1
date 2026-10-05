# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
param(
    [Parameter(Mandatory=$true)][string]$Python,
    [ValidateSet('hydra.training.decision_candidates','hydra.training.decision_rounds','hydra.training.decision_challenges','hydra.training.decision_compare')]
    [string]$Module='hydra.training.decision_rounds',
    [string]$DependencySitePackages='',
    [string[]]$Arguments=@()
)
$ErrorActionPreference='Stop'
if ($DependencySitePackages -and !(Test-Path -LiteralPath $DependencySitePackages -PathType Container)) {
    throw 'DependencySitePackages must be an existing directory.'
}
# Extra existing dependencies are appended, preserving the selected GPU runtime first.
& $Python -c 'import sys,runpy; extra=sys.argv.pop(1); module=sys.argv.pop(1); sys.path.extend([extra] if extra else []); sys.argv[0]=module; runpy.run_module(module,run_name="__main__")' $DependencySitePackages $Module @Arguments
exit $LASTEXITCODE
