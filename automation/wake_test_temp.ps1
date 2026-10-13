# TEMPORARY wake / network / Claude CLI feasibility test (diagnostic only; NOT the competition schedule).
# Run by the one-off scheduled task AI_CUP_WAKE_TEST_TEMP. Writes logs\wake_test\wake_test_YYYYMMDD_HHMMSS.log
# Does NOT: run the Agent, produce a D-Plan, log in anywhere, upload anything, read cookies / tokens / credentials,
# print MAC addresses or SSIDs. Never calls `exit` (no window is closed).
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root 'logs\wake_test'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ('wake_test_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
function W([string]$k, [string]$v) { Add-Content -Path $Log -Encoding UTF8 -Value ('{0,-18} {1}' -f $k, $v) }
function Now() { (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fffzzz') }

W 'START_TIME' (Now)
W 'TRIGGERED_BY' ($(if ($env:AI_CUP_WAKE_TEST_MANUAL) { 'manual' } else { 'task' }))

# ---- power
try {
    $b = Get-CimInstance Win32_Battery -ErrorAction Stop | Select-Object -First 1
    W 'POWER_SOURCE' ($(if ($b.BatteryStatus -eq 2) { 'AC' } elseif ($b) { "BATTERY (status $($b.BatteryStatus))" } else { 'NO_BATTERY' }))
    W 'BATTERY_PERCENT' ([string]$b.EstimatedChargeRemaining)
} catch { W 'POWER_SOURCE' "ERROR $($_.Exception.Message)" }
try {
    $lw = (powercfg /lastwake 2>&1 | Out-String).Trim() -replace '\s+', ' '
    W 'LAST_WAKE' $lw
} catch { W 'LAST_WAKE' 'unavailable' }
try {
    $ev = Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-Power'; Id = 506, 507 } -MaxEvents 4 -ErrorAction Stop |
        ForEach-Object { '{0} id{1}' -f $_.TimeCreated.ToString('HH:mm:ss'), $_.Id }
    W 'STANDBY_EVENTS' (($ev -join '; ') + '  (506=enter modern standby, 507=exit)')
} catch { W 'STANDBY_EVENTS' 'unavailable' }

# ---- Wi-Fi (state only; no SSID / BSSID / MAC)
$wifiUp = $false
for ($i = 0; $i -lt 24; $i++) {                      # up to ~120 s for Wi-Fi to reconnect after wake
    $a = Get-NetAdapter -Name 'Wi-Fi' -ErrorAction SilentlyContinue
    if ($a -and $a.Status -eq 'Up') { $wifiUp = $true; break }
    Start-Sleep -Seconds 5
}
W 'WIFI_STATUS' ($(if ($a) { "$($a.Status) after $($i * 5)s ($($a.InterfaceDescription))" } else { 'ADAPTER_NOT_FOUND' }))

# ---- DNS / HTTPS (public pages only; no login, no cookies)
function TestHttps([string]$name, [string]$url) {
    $ok = $false; $msg = ''
    for ($t = 0; $t -lt 6 -and -not $ok; $t++) {
        try {
            $r = Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
            $ok = $true; $msg = "HTTP $($r.StatusCode)"
        } catch { $msg = $_.Exception.Message; Start-Sleep -Seconds 5 }
    }
    W $name ("{0} {1} [{2}]" -f $(if ($ok) { 'OK' } else { 'FAIL' }), $url, $msg)
}
try { $d = Resolve-DnsName www.twse.com.tw -ErrorAction Stop | Select-Object -First 1; W 'DNS' "OK www.twse.com.tw" }
catch { W 'DNS' "FAIL $($_.Exception.Message)" }
TestHttps 'INTERNET_HTTPS' 'https://www.google.com/'
TestHttps 'ESUN_SITE' 'https://esun-ai-challenge.tw/'
TestHttps 'DATA_SOURCE_TWSE' 'https://www.twse.com.tw/zh/'
TestHttps 'DATA_SOURCE_TPEX' 'https://www.tpex.org.tw/'

# ---- Claude CLI (version + minimal structured smoke through the project's locked provider: no tools,
#      sandbox cwd runtime\claude_cli, no session persistence, prompt contains no repo content)
$py = Join-Path $Root '.venv\Scripts\python.exe'
$smoke = @'
import json, sys
sys.path.insert(0, r"{ROOT}")
from agent.llm.base import LLMRequest
from agent.llm.client import load_llm_config
from agent.llm.providers.claude_cli import ClaudeCodeCLIProvider, resolve_claude_cli
c = resolve_claude_cli()
print("VERSION", c["version"], c["kind"])
p = ClaudeCodeCLIProvider(None, dict(load_llm_config("config/llm_claude_cli.yaml"), enabled=True))
print("AUTH", p.auth().get("loggedIn"), p.auth().get("authMethod"))
p.schema_overrides["wake_smoke"] = {"type": "object", "additionalProperties": False,
    "properties": {"status": {"type": "string", "enum": ["ok"]}}, "required": ["status"]}
r = p.complete(LLMRequest(task="wake_smoke", system="Return the JSON object {\"status\":\"ok\"}. Nothing else.",
    prompt="<INPUT_JSON>{}</INPUT_JSON>", prompt_version="wake_test", timeout=120.0))
o = json.loads(r.text)
print("SMOKE", "OK" if o == {"status": "ok"} else "UNEXPECTED", json.dumps(o), "latency=%.1fs" % r.latency_sec)
'@ -replace '\{ROOT\}', $Root
$tmp = Join-Path $env:TEMP 'ai_cup_wake_smoke.py'
Set-Content -Path $tmp -Value $smoke -Encoding UTF8
Push-Location $Root
try {
    $out = & $py $tmp 2>&1 | Out-String
} catch { $out = "ERROR $($_.Exception.Message)" }
Pop-Location
$ver = ($out -split "`n" | Where-Object { $_ -like 'VERSION*' }) -join ''
$auth = ($out -split "`n" | Where-Object { $_ -like 'AUTH*' }) -join ''
$sm = ($out -split "`n" | Where-Object { $_ -like 'SMOKE*' }) -join ''
W 'CLAUDE_VERSION' ($(if ($ver) { $ver.Trim() } else { 'FAIL' }))
W 'CLAUDE_AUTH' ($(if ($auth) { $auth.Trim() } else { 'FAIL' }))
W 'CLAUDE_SMOKE' ($(if ($sm) { $sm.Trim() } else { 'FAIL ' + (($out -replace '\s+', ' ').Trim()).Substring(0, [Math]::Min(300, (($out -replace '\s+', ' ').Trim()).Length)) }))
W 'CLAUDE_CLI_AVAILABLE' ($(if ($sm -like '*SMOKE OK*') { 'YES' } else { 'NO' }))
Remove-Item $tmp -ErrorAction SilentlyContinue

W 'END_TIME' (Now)
