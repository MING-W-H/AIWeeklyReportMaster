# Register weekly scheduled task (every Friday 15:00) for CRM reminder
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
Unregister-ScheduledTask -TaskName "CRMReminder" -Confirm:$false -ErrorAction SilentlyContinue

# Register weekly task
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batFile = Join-Path $scriptDir "run_crm_reminder.bat"

$action = New-ScheduledTaskAction -Execute $batFile -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "15:00"
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName "CRMReminder" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "CRM Fill-in Reminder - Weekly on Friday at 15:00" -Force | Out-Null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  CRM Reminder scheduled task registered!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Task: CRMReminder" -ForegroundColor Cyan
Write-Host "  Schedule: Every Friday at 15:00" -ForegroundColor Cyan
Write-Host "  User: $env:USERNAME" -ForegroundColor Cyan
Write-Host "  Launcher: $batFile" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Holiday check: ENABLED (skips holidays)" -ForegroundColor Yellow
Write-Host "  Force run: python crm_reminder.py --yes --force" -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to close"
