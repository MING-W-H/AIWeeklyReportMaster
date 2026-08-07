@echo off
REM ============================================================
REM  CRM Reminder - Scheduled Task Launcher (Windows)
REM
REM  This script:
REM    - Activates virtualenv if exists
REM    - Changes to script directory
REM    - Runs crm_reminder.py --yes (send without confirmation)
REM
REM  Run log is appended to logs\crm_reminder.log (already gitignored)
REM
REM  How to register scheduled task (run as Admin):
REM    .\register_crm_reminder.ps1
REM ============================================================

REM Switch to script directory
cd /d "%~dp0"

REM Create logs directory
if not exist "logs" mkdir logs

REM Activate virtualenv if exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [INFO] Activated venv .venv
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [INFO] Activated venv venv
) else (
    echo [INFO] No venv found, using system Python
)

echo [INFO] Starting crm_reminder.py...

REM Run crm_reminder.py (--yes skips confirmation; log appended to logs\crm_reminder.log)
python crm_reminder.py --yes >> "logs\crm_reminder.log" 2>&1

REM Record exit code
set "EXITCODE=%ERRORLEVEL%"
echo [INFO] crm_reminder.py exit code: %EXITCODE%

REM Exit codes:
REM   0  = success / skipped (not Friday or holiday)
REM   1  = config error (dingtalk/reminder not enabled, missing group, missing credentials)
REM   2  = send failed

exit /b %EXITCODE%
