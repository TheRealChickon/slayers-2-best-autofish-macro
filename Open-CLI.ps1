. (Join-Path $PSScriptRoot 'Runtime.ps1')
$fishingPython = Get-FishingPython
$cliScript = Join-Path $PSScriptRoot 'fishing_cli.py'
Start-Process -FilePath $fishingPython -ArgumentList ('"' + $cliScript + '" --color tui') -WorkingDirectory $PSScriptRoot -WindowStyle Normal
