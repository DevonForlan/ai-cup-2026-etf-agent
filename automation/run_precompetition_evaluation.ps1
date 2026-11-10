# AI CUP PRECOMPETITION next-day evaluation (Task Scheduler: AI_CUP_Precompetition_Evaluation_1700, 17:00,
# WakeToRun=False, StartWhenAvailable=True -> same-day catch-up after logon; never replays a previous day).
# Logic in agent/ops/daily_evaluation.py. Evaluates the previous evening's paper prediction with the existing
# deterministic simulator. PRECOMPETITION_PAPER_RUN only: no upload, no submission. Never calls `exit`.
# Manual: .\automation\run_precompetition_evaluation.ps1
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
Set-Location -Path $Root
$LogDir = Join-Path $Root 'logs\evaluation'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Publish-SchedStatus([string]$Task, [string]$Event, [bool]$Sweep = $false) {
    # Issue #65: observability only (never fails / blocks the run): scheduler status -> shared-state branch (+ CC session sweep after the run)
    try { & $Py -m agent.ops.shared_state_scheduler --task $Task --event $Event 2>&1 | Out-Null } catch { }
    if ($Sweep) { try { & $Py (Join-Path $Root 'agent\ops\cc_session_sync.py') sweep 2>&1 | Out-Null } catch { } }
}
Publish-SchedStatus 'evaluation_1700' 'START'
try {
    if (-not (Test-Path $Py)) { throw "python not found: $Py" }
    $out = & $Py -m agent.ops.daily_evaluation 2>&1 | Out-String
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} {1}" -f (Get-Date -Format o), $out.Trim())
}
catch {
    $now = Get-Date -Format o
    $rec = [ordered]@{ evaluation_date = $null; prediction_date = $null; started_at = $now; finished_at = $now;
        status = 'FAILED'; label = 'PRECOMPETITION_PAPER_RUN'; blocked_reason = $null;
        error_message = "wrapper: $($_.Exception.Message)"; log_file = (Join-Path $LogDir 'wrapper.log') }
    $rec | ConvertTo-Json | Set-Content -Path (Join-Path $LogDir 'latest_status.json') -Encoding UTF8
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} FAILED {1}" -f $now, $_.Exception.Message)
}
Publish-SchedStatus 'evaluation_1700' 'END' $true
