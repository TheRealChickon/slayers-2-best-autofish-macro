. (Join-Path $PSScriptRoot 'Runtime.ps1')
& (Get-FishingPython) (Join-Path $PSScriptRoot 'fishing_cli.py') stop
exit $LASTEXITCODE
