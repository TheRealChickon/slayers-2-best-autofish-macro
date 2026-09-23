@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-CLI.ps1" %*
if errorlevel 1 pause
