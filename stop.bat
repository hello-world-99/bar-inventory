@echo off
rem Stops Bar Inventory. Data stays; start.bat starts it again.
cd /d "%~dp0"
docker compose stop
pause
