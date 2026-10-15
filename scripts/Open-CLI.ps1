. (Join-Path $PSScriptRoot 'Runtime.ps1')
$fishingPython = Get-FishingPython
$cliScript = Join-Path $AutofishRoot 'src\fishing_cli.py'
Start-Process -FilePath $fishingPython -ArgumentList ('"' + $cliScript + '" --color tui') -WorkingDirectory $AutofishRoot -WindowStyle Normal
