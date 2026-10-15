# Opens the Autofish app window (src\app_window.py) without a console.
. (Join-Path $PSScriptRoot 'Runtime.ps1')
$fishingPython = Get-FishingPython
$windowPython = Join-Path (Split-Path -Parent $fishingPython) 'pythonw.exe'
if (Test-Path -LiteralPath $windowPython) { $fishingPython = $windowPython }
$appScript = Join-Path $AutofishRoot 'src\app_window.py'
Start-Process -FilePath $fishingPython -ArgumentList ('"' + $appScript + '"') -WorkingDirectory $AutofishRoot -WindowStyle Hidden
