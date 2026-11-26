@echo off
rem Loads the example data (a week of POS days, the owner's day, products running low) into a FRESH install.
rem The app must be running (start.bat).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\examples.ps1"
if errorlevel 1 (
  echo.
  echo Something went wrong, see the message above.
)
pause
