# Register weekly scheduled task (every Monday 10:00)
# Must run as Administrator

$ErrorActionPreference = "Stop"

# Check admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[ERROR] Please run as Administrator" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Remove existing task
Unregister-ScheduledTask -TaskName "AIWeeklyReport" -Confirm:$false -ErrorAction SilentlyContinue

# Register weekly task
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batFile = Join-Path $scriptDir "run_weekly_report.bat"

$action = New-ScheduledTaskAction -Execute $batFile -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "10:00"
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName "AIWeeklyReport" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "AI Weekly Report - Weekly on Monday at 10:00" -Force | Out-Null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Weekly scheduled task registered!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Task: AIWeeklyReport" -ForegroundColor Cyan
Write-Host "  Schedule: Every Monday at 10:00" -ForegroundColor Cyan
Write-Host "  User: $env:USERNAME" -ForegroundColor Cyan
Write-Host "  Launcher: $batFile" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Holiday check: ENABLED (skips holidays)" -ForegroundColor Yellow
Write-Host "  Force run: python weekly_report.py --force" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to close"
