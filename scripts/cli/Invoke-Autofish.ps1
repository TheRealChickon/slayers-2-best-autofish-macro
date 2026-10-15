param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CliArgs)
$ErrorActionPreference = 'Stop'
try {
    $installation = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'installation.json') -Raw | ConvertFrom-Json
    if ($installation.product -ne 'autofish') { throw 'Invalid Autofish installation. Run Install-CLI.cmd again.' }
    $appDirectory = $installation.appDirectory
    $entryPoint = Join-Path $appDirectory 'src\autofish.py'
    if (-not (Test-Path -LiteralPath $entryPoint)) { throw 'Autofish was moved. Run Install-CLI.cmd in its new folder.' }
    . (Join-Path $appDirectory 'scripts\Runtime.ps1')
    $fishingPython = Get-FishingPython
    & $fishingPython $entryPoint @CliArgs
    exit $LASTEXITCODE
} catch { Write-Error $_; exit 1 }
