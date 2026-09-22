. (Join-Path $PSScriptRoot 'Runtime.ps1')
$fishingPython = Get-FishingPython
& $fishingPython (Join-Path $PSScriptRoot 'fishing_cli.py') continue
if ($LASTEXITCODE -ne 0) { throw 'Fishing could not start. Open Fishing CLI for details.' }
