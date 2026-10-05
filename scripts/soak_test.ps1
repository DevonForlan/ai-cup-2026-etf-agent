# Soak test: run the daily pipeline N times (fixture store) and check memory / handles / outputs.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\soak_test.ps1 [-Iterations 100] [-Store fixture|real]
param(
    [int]$Iterations = 100,
    [ValidateSet('fixture', 'real')][string]$Store = 'fixture'
)
. (Join-Path $PSScriptRoot '_common.ps1')
$code = Invoke-AgentPython @('agent\ops\soak.py', '--iterations', "$Iterations", '--store', $Store)
Write-Result 'soak' $code
Write-Host 'Details: reports\round06_soak.csv, reports\round06_soak_summary.json'
