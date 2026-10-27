# Registers the DAILY 07:30 COMPETITION morning-FINAL task (Issue #20): current user, StartWhenAvailable, no wake,
# at most 85 minutes (ends by 08:55). The action has a guard: if automation\run_morning_final.ps1 is missing (Issue #20
# not merged / master not pulled) it writes FAILED + SUBMISSION_STATUS BLOCKED to logs\morning\latest_status.json.
# Does not touch AI_CUP_Precompetition_Evaluation_1700 or AI_CUP_Precompetition_DryRun_1930.
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
$Name = 'AI_CUP_Competition_MorningFinal_0730'
$Wrapper = Join-Path $Root 'automation\run_morning_final.ps1'
$Log = Join-Path $Root 'logs\morning'
$Cmd = "if (Test-Path '$Wrapper') { & '$Wrapper' } else { New-Item -ItemType Directory -Force -Path '$Log' | Out-Null; " +
       "@{ task='$Name'; actual_start_time=(Get-Date -Format o); status='FAILED'; prediction_status='FAILED'; " +
       "submission_status='BLOCKED'; manual_action_required=`$true; " +
       "error_message='WRAPPER_MISSING: automation\run_morning_final.ps1 not in the working copy (Issue #20 not merged / master not pulled)' } " +
       "| ConvertTo-Json | Set-Content -Path '$Log\latest_status.json' -Encoding UTF8 }"
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$Cmd`"") -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]'2026-10-28T07:30:00')
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 85) -MultipleInstances IgnoreNew
$Settings.WakeToRun = $false
Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings -Description 'AI CUP 07:30 COMPETITION morning FINAL + fail-closed submission (Issue #20). Quant v1 unchanged.' -Force | Out-Null
Get-ScheduledTask -TaskName $Name | Select-Object TaskName, State | Format-List
