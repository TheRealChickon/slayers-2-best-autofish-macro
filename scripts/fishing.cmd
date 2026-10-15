@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Invoke-CLI.ps1" %*
exit /b %errorlevel%
