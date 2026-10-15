param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CliArgs)
. (Join-Path $PSScriptRoot 'Runtime.ps1')
try {
    $fishingPython = Get-FishingPython
    & $fishingPython (Join-Path $AutofishRoot 'src\fishing_cli.py') @CliArgs
    exit $LASTEXITCODE
} catch { Write-Error $_; exit 1 }
