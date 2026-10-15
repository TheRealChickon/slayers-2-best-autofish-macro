$ErrorActionPreference = 'Stop'
# Scripts live in scripts\; the app, settings and Python environment are one folder up.
$AutofishRoot = Split-Path -Parent $PSScriptRoot

function Get-FishingPython {
    $localRuntime = Join-Path $AutofishRoot 'runtime.local.json'
    if (Test-Path -LiteralPath $localRuntime) {
        $candidate = (Get-Content -LiteralPath $localRuntime -Raw | ConvertFrom-Json).python
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $candidate = Join-Path $AutofishRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    throw 'Autofish is not installed yet. Double-click Autofish.exe in the download.'
}
