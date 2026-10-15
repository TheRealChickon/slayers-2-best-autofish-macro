param([string]$Ref = 'HEAD')
# Build share\Autofish-<version>.zip from committed files (see share_build.py).
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Runtime.ps1')
& (Get-FishingPython) (Join-Path $PSScriptRoot 'share_build.py') $Ref
