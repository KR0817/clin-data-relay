@echo off
setlocal
cd /d "%~dp0"
"%~dp0Start-Clinical-EDC-Lite.exe" --lite --reset-centre-password
echo.
echo Store the new password before closing this window.
pause
endlocal
