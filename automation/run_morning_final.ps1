# AI CUP COMPETITION 07:30 morning FINAL (Issue #20; Task Scheduler: AI_CUP_Competition_MorningFinal_0730, daily 07:30,
# WakeToRun=False, StartWhenAvailable=True). Logic in agent/ops/morning_final.py: production lock -> morning refresh ->
# latest COMPETITION FINAL (same competition_day pipeline, Quant v1 unchanged) -> supersede only if every gate passes
# before 08:30 -> downstream fail-closed submission runner. Never calls `exit`.
# Manual: .\automation\run_morning_final.ps1
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
Set-Location -Path $Root
$LogDir = Join-Path $Root 'logs\morning'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    if (-not (Test-Path $Py)) { throw "python not found: $Py" }
    if (-not (Test-Path (Join-Path $Root 'agent\ops\morning_final.py'))) { throw 'agent\ops\morning_final.py missing (Issue #20 not merged / master not pulled)' }
    $out = & $Py -m agent.ops.morning_final 2>&1 | Out-String
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} {1}" -f (Get-Date -Format o), $out.Trim())
}
catch {
    $now = Get-Date -Format o
    $rec = [ordered]@{ task = 'AI_CUP_Competition_MorningFinal_0730'; actual_start_time = $now; finished_at = $now;
        status = 'FAILED'; prediction_status = 'FAILED'; submission_status = 'BLOCKED'; manual_action_required = $true;
        error_message = "wrapper: $($_.Exception.Message)"; log_file = (Join-Path $LogDir 'wrapper.log') }
    $rec | ConvertTo-Json | Set-Content -Path (Join-Path $LogDir 'latest_status.json') -Encoding UTF8
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} FAILED {1}" -f $now, $_.Exception.Message)
}
