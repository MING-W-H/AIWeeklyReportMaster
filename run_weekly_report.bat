@echo off
REM ============================================================
REM  AI Weekly Report - Scheduled Task Launcher (Windows)
REM
REM  This script:
REM    - Activates virtualenv if exists
REM    - Changes to script directory
REM    - Runs weekly_report.py
REM
REM  运行日志由程序内部自动生成，每次任务仅一个文件：
REM    logs\{周报名称}.txt   （如 logs\Vue2026.7.27-8.2周报.txt）
REM
REM  How to register scheduled task (run as Admin):
REM    .\register_weekly.ps1
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

echo [INFO] Starting weekly_report.py...
echo [INFO] 运行日志将自动保存至 logs\周报名称.txt

REM Run weekly_report.py（日志由程序内部写入 logs\，每次任务仅生成一个 txt）
python weekly_report.py

REM Record exit code
set "EXITCODE=%ERRORLEVEL%"
echo [INFO] weekly_report.py exit code: %EXITCODE%

REM Exit codes:
REM   0 = success
REM   1 = excel folder error
REM   2 = AI API error
REM   3 = email send error

exit /b %EXITCODE%
