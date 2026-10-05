# End-of-day housekeeping: internal settlement of trade date T (after T close data), then refresh audit/ indexes.
# Archives of each run are already written by competition_day (archive\YYYYMMDD\<run_id>\, immutable).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\archive_daily.ps1 -Date 2026-10-27 [-Initial]
param(
    [Parameter(Mandatory = $true)][string]$Date,
    [switch]$Initial,
    [switch]$NoRefresh
)
. (Join-Path $PSScriptRoot '_common.ps1')
$cmd = @('agent\ops\settle_internal.py', '--date', $Date)
if (-not $NoRefresh) { $cmd += '--refresh' }
if ($Initial) { $cmd += '--initial' }
$code = Invoke-AgentPython $cmd
Write-Result 'settle_internal' $code
$a = Invoke-AgentPython @('agent\ops\audit.py')
Write-Result 'audit' $a
Write-Host "Next: copy the organizer's official settlement for $Date (if published) to data\settlement\$($Date.Replace('-', ''))_official.json" -ForegroundColor Cyan
