param([switch]$SkipInstall, [switch]$NoDesktop, [switch]$NoCLI)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Runtime.ps1')

if (-not $SkipInstall) {
    $fishingVenv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $fishingVenv)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3.12 -m venv (Join-Path $PSScriptRoot '.venv')
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv (Join-Path $PSScriptRoot '.venv')
        } else { throw 'Install Python 3.12 (64-bit) from python.org, then run Setup.cmd again.' }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the environment. Install Python 3.12 (64-bit), then retry.' }
    }
    & $fishingVenv -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Review the message above, then retry Setup.cmd.' }
}
$fishingPython = Get-FishingPython
& $fishingPython (Join-Path $PSScriptRoot 'setup_check.py')
if ($LASTEXITCODE -ne 0) { throw 'Setup checks failed.' }
$localConfig = Join-Path $PSScriptRoot 'config.local.json'
if (-not (Test-Path -LiteralPath $localConfig)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config.example.json') -Destination $localConfig
}
if (-not $NoDesktop) { & (Join-Path $PSScriptRoot 'Install-Desktop.ps1') }
if (-not $NoCLI) { & (Join-Path $PSScriptRoot 'Install-CLI.ps1') }
Write-Host 'Ready. Run autofish start in a new terminal, or open Fishing on your desktop.' -ForegroundColor Green
