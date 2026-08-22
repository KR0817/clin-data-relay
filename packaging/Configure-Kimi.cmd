@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_kimi.ps1" -RuntimeDirectory "%~dp0.runtime"
if errorlevel 1 (
  echo.
  echo Kimi configuration failed. Press any key to close.
  pause >nul
)
endlocal
