. (Join-Path $PSScriptRoot 'Runtime.ps1')
& (Get-FishingPython) (Join-Path $AutofishRoot 'src\fishing_cli.py') stop
exit $LASTEXITCODE
