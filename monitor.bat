@echo off
REM Auto-apply monitor - run this in a separate terminal to watch progress
echo ================================================================
echo   AUTO-APPLY MONITOR
echo   Checking every 60 seconds...
echo   Press Ctrl+C to stop monitoring
echo ================================================================
echo.

:loop
python check_status.py
timeout /t 60 /nobreak >nul
goto loop
