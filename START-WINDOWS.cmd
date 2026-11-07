@echo off
setlocal
cd /d "%~dp0"
echo Flow Studio - independent local app
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0serve-windows.ps1"
if errorlevel 1 pause
