@echo off
REM setup_scheduler.bat — Register auto_apply daily run with Windows Task Scheduler
REM Run this script once as Administrator.
REM
REM What it creates:
REM   Task name : AutoApplyDailyRun
REM   Trigger   : Every day at 7:00 AM (adjust /ST below)
REM   Action    : python scripts/daily_run.py --keyword "data analyst" --location "remote"
REM   Working dir: the auto_apply folder next to this script

setlocal

REM ── Paths ──────────────────────────────────────────────────────────────────────
set PYTHON=%USERPROFILE%\anaconda3\python.exe
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set DAILY_SCRIPT=%PROJECT_DIR%\scripts\daily_run.py

REM ── Task settings ──────────────────────────────────────────────────────────────
set TASK_NAME=AutoApplyDailyRun
set START_TIME=07:00

REM ── Delete existing task if present ────────────────────────────────────────────
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %errorlevel% == 0 (
    echo Removing existing task "%TASK_NAME%"...
    schtasks /delete /tn "%TASK_NAME%" /f
)

REM ── Register new task ──────────────────────────────────────────────────────────
echo Creating scheduled task "%TASK_NAME%" at %START_TIME% daily...

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%DAILY_SCRIPT%\" --keyword \"data analyst\" --location \"remote\"" ^
  /sc daily ^
  /st %START_TIME% ^
  /sd %date% ^
  /rl highest ^
  /f

if %errorlevel% == 0 (
    echo.
    echo Task created successfully.
    echo.
    echo To run it immediately:
    echo   schtasks /run /tn "%TASK_NAME%"
    echo.
    echo To edit the keyword/location, modify this script and re-run it.
    echo To remove the task:
    echo   schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo.
    echo ERROR: Task creation failed.
    echo Try running this script as Administrator.
)

endlocal
pause
