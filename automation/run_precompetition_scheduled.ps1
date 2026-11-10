# AI CUP PRECOMPETITION daily dry-run (Task Scheduler: AI_CUP_Precompetition_DryRun_1930, 19:30, WakeToRun=False,
# StartWhenAvailable=True -> a missed 19:30 run is caught up after the next logon / wake on the same day).
# Logic (date window, already-PASS skip, cross-day skip, network retries, Claude precheck, status JSON) lives in
# agent/ops/scheduled_run.py. PRECOMPETITION only: dry-run, never uploads, never submits. Never calls `exit`.
# Manual: .\automation\run_precompetition_scheduled.ps1 [-SetupTest]
param([switch]$SetupTest)
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
Set-Location -Path $Root
$LogDir = Join-Path $Root 'logs\scheduled'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Publish-SchedStatus([string]$Task, [string]$Event, [bool]$Sweep = $false) {
    # Issue #65: observability only (never fails / blocks the run): scheduler status -> shared-state branch (+ CC session sweep after the run)
    try { & $Py -m agent.ops.shared_state_scheduler --task $Task --event $Event 2>&1 | Out-Null } catch { }
    if ($Sweep) { try { & $Py (Join-Path $Root 'agent\ops\cc_session_sync.py') sweep 2>&1 | Out-Null } catch { } }
}
Publish-SchedStatus 'dryrun_1930' 'START'
$argsList = @('-m', 'agent.ops.scheduled_run')
if ($SetupTest) { $argsList += '--setup-test' }
try {
    if (-not (Test-Path $Py)) { throw "python not found: $Py" }
    $out = & $Py @argsList 2>&1 | Out-String
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} {1}" -f (Get-Date -Format o), $out.Trim())
}
catch {
    # the Python helper could not even start: record a FAILED status so the check script shows it
    $now = Get-Date -Format o
    $rec = [ordered]@{ scheduled_time = $null; actual_start_time = $now; finished_at = $now; run_delay_minutes = $null;
        trade_date = $null; status = 'FAILED'; network = $null; network_retries = $null; claude = $null;
        claude_fallback = $null; data_refresh = $null; etf_freshness = $null; quant = $null; active_share = $null;
        grounding = $null; dplan_version = $null; dplan_validation = $null; final_candidate = $null;
        blocked_reason = $null; error_message = "wrapper: $($_.Exception.Message)"; log_file = (Join-Path $LogDir 'wrapper.log') }
    $rec | ConvertTo-Json | Set-Content -Path (Join-Path $LogDir 'latest_status.json') -Encoding UTF8
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} FAILED {1}" -f $now, $_.Exception.Message)
}
Publish-SchedStatus 'dryrun_1930' 'END' $true
