# Daily data refresh for trade date T (T-1 market data + overnight data + ETF snapshot + MOPS first-seen).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\refresh_daily.ps1 [-Date 2026-10-27] [-Only twse_prices,tpex_prices]
param(
    [string]$Date,
    [string]$Only,
    [string]$Skip
)
. (Join-Path $PSScriptRoot '_common.ps1')
$td = Get-TradeDate $Date
$cmd = @('agent\ops\refresh_daily.py', '--date', $td)
if ($Only) { $cmd += @('--only', $Only) }
if ($Skip) { $cmd += @('--skip', $Skip) }
Write-Host "Data refresh for trade date $td" -ForegroundColor Cyan
$code = Invoke-AgentPython $cmd
Write-Result 'refresh_daily' $code
Write-Host "Report: logs\ops\$($td.Replace('-', ''))\data_health.md"
