@echo off
setlocal
cd /d "%~dp0"
"%~dp0..\Start-Clinical-EDC-Lite.exe" --lite --port 8000
if errorlevel 1 (
  echo.
  echo Startup failed. Review the message above, then press any key to close.
  pause >nul
)
endlocal
