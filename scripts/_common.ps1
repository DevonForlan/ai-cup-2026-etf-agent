# Shared helpers for the ops scripts (Windows PowerShell 5.1 compatible). Dot-source only.
# Never calls `exit` (the operator's console must stay open). No Task Scheduler, no upload.

$Script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Script:Python = Join-Path $Script:ProjectRoot '.venv\Scripts\python.exe'

function Invoke-AgentPython {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    if (-not (Test-Path $Script:Python)) {
        Write-Host "Python venv not found: $Script:Python" -ForegroundColor Red
        return 99
    }
    $env:PYTHONIOENCODING = 'utf-8'
    Push-Location $Script:ProjectRoot
    try {
        & $Script:Python @Arguments | Out-Host
        return $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

function Get-TradeDate {
    param([string]$Date)
    if ($Date) { return $Date }
    # Default: next weekday after today (the trade date whose D-Plan is prepared this evening).
    $d = (Get-Date).AddDays(1)
    while ($d.DayOfWeek -eq 'Saturday' -or $d.DayOfWeek -eq 'Sunday') { $d = $d.AddDays(1) }
    return $d.ToString('yyyy-MM-dd')
}

function Write-Result {
    param([string]$Step, [int]$Code)
    if ($Code -eq 0) {
        Write-Host "[$Step] OK" -ForegroundColor Green
    }
    else {
        Write-Host "[$Step] NOT OK (exit code $Code) - see logs\ops and docs\EMERGENCY_RUNBOOK.md" -ForegroundColor Yellow
    }
}
