@echo off
setlocal
cd /d "%~dp0"
echo.
echo Mystery Coloring Studio - local startup
if not exist "dist\index.html" (
  echo Missing dist\index.html. Please extract the full ZIP first.
  pause
  exit /b 1
)
echo Opening local server on 127.0.0.1...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0server-local.ps1"
if errorlevel 1 (
  echo.
  echo Could not start local server. See instructions in README_AR.md.
  pause
)
