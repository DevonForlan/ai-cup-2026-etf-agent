# AI CUP Day-1 18:00 verification (Task Scheduler: AI_CUP_Day1_Verify_1800, one-off 2026-10-26 18:00 +08:00).
# READ ONLY: runs agent.ops.day1_verify; never edits config, commits, pushes, generates a decision or touches the
# portal (Issue #16). Any failure writes RUN_MODE_SWITCH_STATUS = FAIL to logs\ops\day1\latest.json (no silent failure).
$Root = 'C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽'
Set-Location -Path $Root
$LogDir = Join-Path $Root 'logs\ops\day1'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try {
    if (-not (Test-Path $Py)) { throw "python not found: $Py" }
    $out = & $Py -m agent.ops.day1_verify 2>&1 | Out-String
    $code = $LASTEXITCODE
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} exit={1}`n{2}" -f (Get-Date -Format o), $code, $out.Trim())
    exit $code
}
catch {
    $now = Get-Date -Format o
    $rec = [ordered]@{ tool = 'day1_verify'; checked_at = $now; RUN_MODE_SWITCH_STATUS = 'FAIL'; MANUAL_ACTION_REQUIRED = 'YES';
        failure_reasons = @("wrapper: $($_.Exception.Message)") }
    $rec | ConvertTo-Json | Set-Content -Path (Join-Path $LogDir 'latest.json') -Encoding UTF8
    Add-Content -Path (Join-Path $LogDir 'wrapper.log') -Encoding UTF8 -Value ("{0} FAILED {1}" -f $now, $_.Exception.Message)
    exit 2
}
