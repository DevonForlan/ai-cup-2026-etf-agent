# Registers the ONE-OFF read-only Day-1 verification task (Issue #16): 2026-10-26 18:00 +08:00, current user, no wake,
# StartWhenAvailable. The action has a guard: if automation\run_day1_verification.ps1 is missing (master not checked out
# yet), it still writes RUN_MODE_SWITCH_STATUS = FAIL to logs\ops\day1\latest.json. Does not touch the 17:00 / 19:30 tasks.
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
$Name = 'AI_CUP_Day1_Verify_1800'
$Wrapper = Join-Path $Root 'automation\run_day1_verification.ps1'
$Log = Join-Path $Root 'logs\ops\day1'
$Cmd = "if (Test-Path '$Wrapper') { & '$Wrapper'; exit `$LASTEXITCODE } else { New-Item -ItemType Directory -Force -Path '$Log' | Out-Null; " +
       "@{ tool='day1_verify'; checked_at=(Get-Date -Format o); RUN_MODE_SWITCH_STATUS='FAIL'; MANUAL_ACTION_REQUIRED='YES'; " +
       "failure_reasons=@('WRAPPER_MISSING: automation\run_day1_verification.ps1 not in the working copy (master with Issue #16 not checked out)') } " +
       "| ConvertTo-Json | Set-Content -Path '$Log\latest.json' -Encoding UTF8; exit 2 }"
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$Cmd`"") -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Once -At ([datetime]'2026-10-26T18:00:00')
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$Settings.WakeToRun = $false
Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings -Description 'AI CUP Day-1 read-only verification (Issue #16). No config edit, no decision, no portal.' -Force | Out-Null
Get-ScheduledTask -TaskName $Name | Select-Object TaskName, State | Format-List
