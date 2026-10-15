$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$fishingDesktop = [Environment]::GetFolderPath('Desktop')
$fishingShell = New-Object -ComObject WScript.Shell
$fishingPowerShell = Join-Path $PSHOME 'powershell.exe'
foreach ($entry in @(
    @{Name='Fishing'; Script='Open-Controls.ps1'; Description='Fishing inventory, controls and live log'},
    @{Name='Fishing CLI'; Script='Open-CLI.ps1'; Description='Keyboard fishing dashboard'},
    @{Name='Start Fishing'; Script='Start-Fishing.ps1'; Description='Continue fishing with saved counters'}
)) {
    $shortcut = $fishingShell.CreateShortcut((Join-Path $fishingDesktop ($entry.Name+'.lnk')))
    $shortcut.TargetPath = $fishingPowerShell
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+(Join-Path $PSScriptRoot $entry.Script)+'"'
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = $entry.Description
    $shortcut.WindowStyle = 7
    $shortcut.IconLocation = (Join-Path $root 'assets\fishing.ico')+',0'
    $shortcut.Save()
    Write-Host ('Desktop: '+$entry.Name)
}
