@echo off
rem Rebuild Autofish.exe. Needs Zig (pip install ziglang).
cd /d "%~dp0"
python -m ziglang cc -target x86_64-windows-gnu -Os -s -municode -Wl,--subsystem,windows autofish_launcher.c autofish.rc -o Autofish.exe
