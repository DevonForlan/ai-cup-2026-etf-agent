# Shows the result of the last AI CUP precompetition scheduled run. Read-only; never calls `exit`.
# Usage: .\automation\check_last_scheduled_run.ps1
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Push-Location $Root
$c = (& $Py -m agent.ops.scheduled_run --check 2>$null | Out-String) | ConvertFrom-Json
Pop-Location
$l = $c.latest
$info = Get-ScheduledTaskInfo -TaskName 'AI_CUP_Precompetition_DryRun_1930' -ErrorAction SilentlyContinue
function Show($k, $v) { Write-Host ('{0,-30} {1}' -f $k, $(if ($null -eq $v -or "$v" -eq '') { '-' } else { $v })) }
Show 'Scheduled Time' $(if ($l -and $c.status -ne 'MISSED') { $l.scheduled_time } else { $c.scheduled_time })
Show 'Actual Run Time' $(if ($c.status -ne 'MISSED') { $l.actual_start_time })
Show 'Delay' $(if ($c.status -ne 'MISSED' -and $l) { "$($l.run_delay_minutes) min" })
Show 'Task Scheduler Last Run Time' $(if ($info) { $info.LastRunTime })
Show 'Task Scheduler Last Result' $(if ($info) { '0x{0:X}' -f $info.LastTaskResult })
Show 'Status' $c.status
Show 'Network' $(if ($c.status -ne 'MISSED') { $l.network })
Show 'Claude' $(if ($c.status -ne 'MISSED') { "$($l.claude) $($l.claude_version)" })
Show 'ETF Freshness' $(if ($c.status -ne 'MISSED') { $l.etf_freshness })
Show 'D-Plan Validation' $(if ($c.status -ne 'MISSED') { $l.dplan_validation })
Show 'Final Candidate' $(if ($c.status -ne 'MISSED') { $l.final_candidate })
Show 'Blocked Reason' $(if ($c.status -ne 'MISSED') { $l.blocked_reason })
Show 'Log File' $(if ($c.status -ne 'MISSED') { $l.log_file })
$color = if ($c.recommended_action -eq 'NONE') { 'Green' } else { 'Yellow' }
Write-Host ('{0,-30} {1}' -f 'Recommended Action', $c.recommended_action) -ForegroundColor $color
