# Verify a release candidate SHA (strategy freeze hash, official inputs, config/prompt hashes, smoke tests in a
# temporary git worktree). Never checks out, resets or modifies the working tree.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\verify_release.ps1 -Sha <git sha> [-NoSmoke]
param(
    [Parameter(Mandatory = $true)][string]$Sha,
    [switch]$NoSmoke
)
. (Join-Path $PSScriptRoot '_common.ps1')
$cmd = @('agent\ops\verify_release.py', '--sha', $Sha)
if (-not $NoSmoke) { $cmd += '--smoke' }
$code = Invoke-AgentPython $cmd
Write-Result 'verify_release' $code
