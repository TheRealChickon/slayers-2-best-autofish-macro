. (Join-Path $PSScriptRoot 'Runtime.ps1')
$fishingPython = Get-FishingPython
$fishingWindowPython = Join-Path (Split-Path -Parent $fishingPython) 'pythonw.exe'
if (Test-Path -LiteralPath $fishingWindowPython) { $fishingPython = $fishingWindowPython }
$controlScript = Join-Path $AutofishRoot 'src\command_window.py'
Start-Process -FilePath $fishingPython -ArgumentList ('"' + $controlScript + '"') -WorkingDirectory $AutofishRoot -WindowStyle Hidden
