param([switch]$SkipInstall, [switch]$NoDesktop, [switch]$NoCLI)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Runtime.ps1')

if (-not $SkipInstall) {
    $fishingVenv = Join-Path $AutofishRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $fishingVenv)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3.12 -m venv (Join-Path $AutofishRoot '.venv')
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -m venv (Join-Path $AutofishRoot '.venv')
        } else { throw 'Install Python 3.12 (64-bit) from python.org, then run Setup.cmd again.' }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the environment. Install Python 3.12 (64-bit), then retry.' }
    }
    & $fishingVenv -m pip install -r (Join-Path $AutofishRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Review the message above, then retry Setup.cmd.' }
}
$fishingPython = Get-FishingPython
& $fishingPython (Join-Path $AutofishRoot 'src\setup_check.py')
if ($LASTEXITCODE -ne 0) { throw 'Setup checks failed.' }
$localConfig = Join-Path $AutofishRoot 'config.local.json'
if (-not (Test-Path -LiteralPath $localConfig)) {
    Copy-Item -LiteralPath (Join-Path $AutofishRoot 'config.example.json') -Destination $localConfig
}
if (-not $NoDesktop) { & (Join-Path $PSScriptRoot 'Install-Desktop.ps1') }
if (-not $NoCLI) { & (Join-Path $PSScriptRoot 'Install-CLI.ps1') }
Write-Host 'Ready. Run autofish start in a new terminal, or open Fishing on your desktop.' -ForegroundColor Green
