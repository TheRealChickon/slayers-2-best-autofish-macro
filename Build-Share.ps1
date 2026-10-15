param([string]$Ref = 'HEAD', [string]$OutDirectory = (Join-Path $PSScriptRoot 'share'))
# Build a zip of the tracked app files for someone without GitHub access.
# Only committed files go in, so local settings, logs, stats and the webhook never do.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $sha = (git rev-parse --short $Ref).Trim()
    $version = (Get-Date -Format 'yyyy.MM.dd-HHmm') + '-' + $sha
    New-Item -ItemType Directory -Force -Path $OutDirectory | Out-Null
    $zip = Join-Path $OutDirectory "Autofish-$version.zip"
    $staging = Join-Path ([IO.Path]::GetTempPath()) "autofish-share-$sha"
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Path $staging | Out-Null
    $tar = Join-Path $staging 'app.tar'
    git archive --format=tar -o $tar $Ref
    if ($LASTEXITCODE -ne 0) { throw 'git archive failed' }
    $app = Join-Path $staging 'Autofish'
    New-Item -ItemType Directory -Path $app | Out-Null
    & (Join-Path $env:SystemRoot "System32	ar.exe") -xf $tar -C $app
    if ($LASTEXITCODE -ne 0) { throw "tar extraction failed" }
    Remove-Item -LiteralPath $tar
    foreach ($name in @('CLAUDE.md', 'AGENTS.md', 'CONTRIBUTING.md', 'tests', '.gitignore')) {
        $path = Join-Path $app $name
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
    Get-ChildItem -LiteralPath $app -Recurse -Include *.mp4, *.avi | Remove-Item -Force
    Set-Content -LiteralPath (Join-Path $app 'VERSION') -Value $version -Encoding ascii
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }
    Compress-Archive -Path (Join-Path $app '*') -DestinationPath $zip
    Remove-Item -LiteralPath $staging -Recurse -Force
    Write-Host $zip
} finally { Pop-Location }
