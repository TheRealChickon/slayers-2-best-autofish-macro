$ErrorActionPreference = 'Stop'

function Get-FishingPython {
    $localRuntime = Join-Path $PSScriptRoot 'runtime.local.json'
    if (Test-Path -LiteralPath $localRuntime) {
        $candidate = (Get-Content -LiteralPath $localRuntime -Raw | ConvertFrom-Json).python
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    $candidate = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    throw 'Run Setup.cmd first to install Fishing.'
}
