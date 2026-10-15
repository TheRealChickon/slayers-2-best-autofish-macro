@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Invoke-CLI.ps1" route record
if errorlevel 1 pause
