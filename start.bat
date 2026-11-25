@echo off
rem Starts Bar Inventory on this computer and opens it in the browser.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 (
  echo.
  echo Something went wrong, see the message above.
)
pause
