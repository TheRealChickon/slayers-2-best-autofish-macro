param([string]$Target = (Join-Path $env:LOCALAPPDATA 'Autofish\app'), [switch]$NoDesktop, [switch]$NoCLI)
# Install or update Autofish from this unzipped folder. Settings (config.local.json),
# run data and stats (data\), the webhook and the Python environment are kept.
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$Target = [IO.Path]::GetFullPath($Target)
$version = if (Test-Path -LiteralPath (Join-Path $source 'VERSION')) { (Get-Content -LiteralPath (Join-Path $source 'VERSION') -Raw).Trim() } else { 'unknown' }
Write-Host "Autofish $version -> $Target" -ForegroundColor Cyan

function Find-Python {
    # A missing runtime makes py.exe write to stderr; that must not stop the installer.
    # No double quotes: Windows PowerShell 5.1 strips them from native arguments.
    $check = 'import sys,struct;assert sys.version_info>=(3,11) and struct.calcsize(chr(80))==8;print(sys.executable)'
    foreach ($candidate in @(@('py', '-3.12'), @('py', '-3.11'), @('py', '-3'), @('python'))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        try {
            $ErrorActionPreference = 'Continue'
            $arguments = @($candidate | Select-Object -Skip 1) + @('-c', $check)
            $path = & $candidate[0] @arguments 2>$null
            if ($LASTEXITCODE -eq 0 -and $path) { return ($path | Select-Object -Last 1).Trim() }
        } catch { } finally { $ErrorActionPreference = 'Stop' }
    }
    $local = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path -LiteralPath $local) { return $local }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host 'Installing Python 3.12 (64-bit, current user only)...' -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
    }
    $python = Find-Python
    if (-not $python) {
        $installer = Join-Path $env:TEMP 'python-3.12-amd64.exe'
        Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
        Start-Process -FilePath $installer -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1' -Wait
        $python = Find-Python
    }
    if (-not $python) { throw 'Python 3.12 could not be installed. Install it from python.org (64-bit), then run Install.cmd again.' }
}

# Copy the app over the previous version; user files are never in the zip, so they stay.
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$keep = @('config.local.json', 'runtime.local.json', 'baitbot.local.json')
Get-ChildItem -LiteralPath $source -Force | Where-Object { $_.Name -notin $keep -and $_.Name -notin @('data', '.venv') } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
}

$venv = Join-Path $Target '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venv)) {
    & $python -m venv (Join-Path $Target '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& $venv -m pip install --disable-pip-version-check -q -r (Join-Path $Target 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installing dependencies failed; check the internet connection and run Install.cmd again.' }
& (Join-Path $Target 'Setup.ps1') -SkipInstall -NoDesktop:$NoDesktop -NoCLI:$NoCLI
Write-Host "Autofish $version is installed. Open a new terminal and run: autofish tui" -ForegroundColor Green
