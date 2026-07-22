@echo off
REM ============================================================
REM  AI Weekly Report - Scheduled Task Launcher (Windows)
REM
REM  This script:
REM    - Activates virtualenv if exists
REM    - Changes to script directory
REM    - Runs weekly_report.py
REM    - Writes logs to logs\weekly_report_YYYYMMDD_HHMMSS.log
REM
REM  How to register scheduled task (run as Admin):
REM    .\register_weekly.ps1
REM ============================================================

REM Switch to script directory
cd /d "%~dp0"

REM Create logs directory
if not exist "logs" mkdir logs

REM Generate log filename with timestamp
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "datetime=%%a"
set "LOGDATE=%datetime:~0,8%"
set "LOGTIME=%datetime:~8,6%"
set "LOGFILE=logs\weekly_report_%LOGDATE%_%LOGTIME%.log"

REM Write header
echo ============================================================ > "%LOGFILE%"
echo AI Weekly Report - Scheduled Run >> "%LOGFILE%"
echo Start time: %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM Activate virtualenv if exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat >> "%LOGFILE%" 2>&1
    echo [INFO] Activated venv .venv >> "%LOGFILE%"
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat >> "%LOGFILE%" 2>&1
    echo [INFO] Activated venv venv >> "%LOGFILE%"
) else (
    echo [INFO] No venv found, using system Python >> "%LOGFILE%"
)

REM Run weekly_report.py
echo [INFO] Starting weekly_report.py... >> "%LOGFILE%"
echo. >> "%LOGFILE%"

python weekly_report.py >> "%LOGFILE%" 2>&1

REM Record exit code
set "EXITCODE=%ERRORLEVEL%"
echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo End time: %date% %time% >> "%LOGFILE%"
echo Exit code: %EXITCODE% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

REM Exit codes:
REM   0 = success
REM   1 = excel folder error
REM   2 = AI API error
REM   3 = email send error

exit /b %EXITCODE%
