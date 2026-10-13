# Shows the last AI CUP precompetition evaluation (PRECOMPETITION_PAPER_RUN). Read-only; never calls `exit`.
# Usage: .\automation\check_last_evaluation.ps1
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Push-Location $Root
$c = (& $Py -m agent.ops.daily_evaluation --check 2>$null | Out-String) | ConvertFrom-Json
Pop-Location
$l = $c.latest
$miss = $c.status -eq 'MISSED'
function Show($k, $v) { Write-Host ('{0,-20} {1}' -f $k, $(if ($null -eq $v -or "$v" -eq '') { '-' } else { $v })) }
function Pct($x) { if ($null -eq $x) { '-' } else { '{0:P2}' -f [double]$x } }
Write-Host 'PRECOMPETITION_PAPER_RUN (not an official competition result)' -ForegroundColor DarkGray
Show 'Evaluation Date' $(if ($miss) { $c.evaluation_date } else { $l.evaluation_date })
Show 'Prediction Date' $(if (-not $miss) { $l.prediction_date })
Show 'Status' $c.status
Show 'NAV' $(if (-not $miss -and $l.nav) { '{0:N0}' -f [double]$l.nav })
Show 'Daily Return' $(if (-not $miss) { Pct $l.daily_return })
Show 'Cumulative Return' $(if (-not $miss) { Pct $l.cumulative_return })
Show 'MDD' $(if (-not $miss) { Pct $l.mdd })
Show 'Turnover' $(if (-not $miss) { Pct $l.turnover })
Show 'Compliance' $(if (-not $miss) { $l.compliance })
Show 'Report' $(if (-not $miss) { $l.report_file })
if (-not $miss -and $l.blocked_reason) { Show 'Blocked Reason' $l.blocked_reason }
$color = if ($c.recommended_action -eq 'NONE') { 'Green' } else { 'Yellow' }
Write-Host ('{0,-20} {1}' -f 'Recommended Action', $c.recommended_action) -ForegroundColor $color
