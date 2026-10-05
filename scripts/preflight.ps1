# Preflight checks (PASS / WARN / BLOCK) for trade date T.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1 [-Date 2026-10-27] [-Mode competition]
param(
    [string]$Date,
    [ValidateSet('dry-run', 'competition')][string]$Mode = 'dry-run',
    [string]$LlmConfig,
    [ValidateSet('prod')][string]$CompetitionProfile,
    [switch]$Initial
)
. (Join-Path $PSScriptRoot '_common.ps1')
$td = Get-TradeDate $Date
$cmd = @('agent\ops\preflight.py', '--date', $td, '--mode', $Mode)
if ($LlmConfig) { $cmd += @('--llm-config', $LlmConfig) }
if ($CompetitionProfile) { $cmd += @('--competition-profile', $CompetitionProfile) }
if ($Initial) { $cmd += '--initial' }
$code = Invoke-AgentPython $cmd
Write-Result 'preflight' $code
