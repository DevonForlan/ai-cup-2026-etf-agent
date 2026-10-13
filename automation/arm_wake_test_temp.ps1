# Arms the TEMPORARY wake test: trigger = now + N minutes (default 5), then enables AI_CUP_WAKE_TEST_TEMP.
# Run it right before closing the lid. Diagnostic only; never calls `exit`.
param([int]$Minutes = 5)
$t = (Get-Date).AddMinutes($Minutes)
Set-ScheduledTask -TaskName 'AI_CUP_WAKE_TEST_TEMP' -Trigger (New-ScheduledTaskTrigger -Once -At $t) | Out-Null
Enable-ScheduledTask -TaskName 'AI_CUP_WAKE_TEST_TEMP' | Out-Null
$i = Get-ScheduledTaskInfo -TaskName 'AI_CUP_WAKE_TEST_TEMP'
Write-Host ("AI_CUP_WAKE_TEST_TEMP armed for {0:yyyy-MM-dd HH:mm:ss} (next run {1}). Close the lid / put the PC to sleep now." -f $t, $i.NextRunTime) -ForegroundColor Yellow
