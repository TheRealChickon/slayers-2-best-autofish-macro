param(
    [string]$BinDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\Autofish\bin'),
    [switch]$NoPath,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$BinDirectory = [IO.Path]::GetFullPath($BinDirectory)
$manifestPath = Join-Path $BinDirectory 'installation.json'
$managedNames = @('autofish.cmd', 'Invoke-Autofish.ps1', 'installation.json')
$previous = $null
if (Test-Path -LiteralPath $manifestPath) {
    $previous = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($previous.product -ne 'autofish') { throw 'The destination belongs to another application.' }
} elseif (@($managedNames | Where-Object { Test-Path -LiteralPath (Join-Path $BinDirectory $_) }).Count) {
    throw 'The destination contains unmanaged files; nothing was replaced.'
}

function Normalize-PathEntry([string]$Value) {
    return [Environment]::ExpandEnvironmentVariables($Value.Trim().Trim('"')).TrimEnd('\', '/').ToLowerInvariant()
}
function Notify-EnvironmentChange {
    if (-not ('Autofish.EnvironmentUpdate' -as [type])) {
        Add-Type -Namespace Autofish -Name EnvironmentUpdate -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode, SetLastError=true)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint msg, System.UIntPtr wParam, string text, uint flags, uint timeout, out System.UIntPtr result);
'@
    }
    $result = [UIntPtr]::Zero
    [void][Autofish.EnvironmentUpdate]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, 'Environment', 2, 1000, [ref]$result)
}
$normalizedBin = Normalize-PathEntry $BinDirectory
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$userEntries = @($userPath -split ';' | Where-Object { $_ -ne '' })
$inUserPath = @($userEntries | Where-Object { (Normalize-PathEntry $_) -eq $normalizedBin }).Count -gt 0

if ($Uninstall) {
    if (-not $previous) { Write-Host 'Autofish command is not installed here.'; return }
    if (-not $NoPath -and $previous.pathAdded -and $inUserPath) {
        $kept = @($userEntries | Where-Object { (Normalize-PathEntry $_) -ne $normalizedBin })
        [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
        $env:Path = (@($env:Path -split ';' | Where-Object { (Normalize-PathEntry $_) -ne $normalizedBin }) -join ';')
        Notify-EnvironmentChange
    }
    # Only our three named files; never remove the application or run data.
    foreach ($name in $managedNames) { Remove-Item -LiteralPath (Join-Path $BinDirectory $name) -ErrorAction SilentlyContinue }
    Write-Host 'Autofish command removed. Application and fishing data kept.'
    return
}

. (Join-Path $PSScriptRoot 'Runtime.ps1')
$null = Get-FishingPython
if (-not (Test-Path -LiteralPath (Join-Path $AutofishRoot 'src\autofish.py'))) { throw 'Missing src\autofish.py.' }
New-Item -ItemType Directory -Path $BinDirectory -Force | Out-Null
foreach ($name in @('autofish.cmd', 'Invoke-Autofish.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot ('cli\' + $name)) -Destination (Join-Path $BinDirectory $name) -Force
}
$added = (-not $NoPath -and -not $inUserPath) -or ($previous -and $previous.pathAdded)
@{ product='autofish'; schema=1; appDirectory=$AutofishRoot; pathAdded=[bool]$added } |
    ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8
if (-not $NoPath -and -not $inUserPath) {
    $newPath = if ($userPath) { $userPath.TrimEnd(';') + ';' + $BinDirectory } else { $BinDirectory }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Notify-EnvironmentChange
}
if (-not $NoPath -and -not (@($env:Path -split ';' | Where-Object { (Normalize-PathEntry $_) -eq $normalizedBin }).Count)) {
    $env:Path += ';' + $BinDirectory
}
Write-Host 'Installed. Open a new terminal and run: autofish start' -ForegroundColor Green
