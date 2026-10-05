# Backup of the operational state (config, settlement ledger, observations, submissions, archive manifests,
# audit, logs\ops, daily reports, templates). Never includes .env / API keys or raw market data.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\backup_competition_state.ps1 [-Dest D:\backup]
param([string]$Dest)
. (Join-Path $PSScriptRoot '_common.ps1')
$cmd = @('agent\ops\backup.py', 'backup')
if ($Dest) { $cmd += @('--dest', $Dest) }
$code = Invoke-AgentPython $cmd
Write-Result 'backup' $code
Write-Host 'Copy the zip to a second location (USB / cloud drive approved by IT). Restore: agent\ops\backup.py restore'
