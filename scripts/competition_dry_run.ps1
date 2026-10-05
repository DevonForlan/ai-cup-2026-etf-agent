# One-command competition day run: refresh -> settlement reconciliation -> preflight -> Quant v1 -> D-Plan ->
# validation -> package -> FINAL_CANDIDATE -> archive -> healthcheck. NEVER uploads anything.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\competition_dry_run.ps1 -TeamId TEAM_TEST [-Date 2026-10-27]
#   ... -Mode competition -TeamId TEAM_042      (real day: still produces only a READY_TO_SUBMIT package)
param(
    [Parameter(Mandatory = $true)][string]$TeamId,
    [string]$Date,
    [ValidateSet('dry-run', 'competition', 'historical')][string]$Mode = 'dry-run',
    [string]$LlmConfig,
    [string]$ReplayRun,
    [switch]$SkipRefresh,
    [switch]$Initial
)
. (Join-Path $PSScriptRoot '_common.ps1')
$td = Get-TradeDate $Date
$cmd = @('agent\competition_day.py', '--date', $td, '--team-id', $TeamId, '--mode', $Mode)
if ($LlmConfig) { $cmd += @('--llm-config', $LlmConfig) }
if ($ReplayRun) { $cmd += @('--replay-run', $ReplayRun) }
if ($SkipRefresh) { $cmd += '--skip-refresh' }
if ($Initial) { $cmd += '--initial' }
$code = Invoke-AgentPython $cmd
Write-Result 'competition_day' $code
$hcMode = 'dry-run'
if ($Mode -eq 'competition') { $hcMode = 'competition' }
$hc = Invoke-AgentPython @('agent\ops\healthcheck.py', '--date', $td, '--mode', $hcMode)
Write-Result 'healthcheck' $hc
$final = Join-Path $Script:ProjectRoot ("submissions\" + $td.Replace('-', '') + "\FINAL_CANDIDATE.txt")
if (Test-Path $final) {
    Write-Host ''
    Get-Content $final -Encoding UTF8 | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
}
else {
    Write-Host "No FINAL_CANDIDATE for $td - do NOT upload anything. See docs\EMERGENCY_RUNBOOK.md" -ForegroundColor Red
}
