@echo off
rem Autofish managed command shim
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Invoke-Autofish.ps1" %*
exit /b %errorlevel%
