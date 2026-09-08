[CmdletBinding()]
param([ValidateSet("Block", "Allow", "Status")][string]$Mode = "Status")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Scheduler.Common.ps1")

$ruleName = "Siligent Scheduler - Block Docker Internet"
if ($Mode -in @("Block", "Allow")) { Assert-SchedulerAdministrator }

if ($Mode -eq "Allow") {
    Get-NetFirewallRule -DisplayName "$ruleName *" -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    Write-Host "[network-policy] Siligent-managed Docker egress rules removed."
    exit 0
}

$paths = @(
    "$env:ProgramFiles\Docker\Docker\resources\com.docker.backend.exe",
    "$env:ProgramFiles\Docker\Docker\resources\com.docker.vpnkit.exe"
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
if ($paths.Count -lt 1) { throw "Docker Desktop networking executables were not found." }

if ($Mode -eq "Block") {
    Get-NetFirewallRule -DisplayName "$ruleName *" -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    $index = 0
    foreach ($path in $paths) {
        $index += 1
        New-NetFirewallRule -DisplayName "$ruleName $index" -Direction Outbound `
            -Action Block -Enabled True -Profile Any -Program $path `
            -RemoteAddress Internet | Out-Null
    }
    try {
        Invoke-SchedulerBash -Arguments @("./scripts/verify_no_egress.sh")
    } catch {
        Get-NetFirewallRule -DisplayName "$ruleName *" -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule
        throw "Egress verification failed; newly created rules were rolled back. $($_.Exception.Message)"
    }
    Write-Host "[network-policy] Docker public-internet access is blocked and verified."
    exit 0
}

$rules = @(Get-NetFirewallRule -DisplayName "$ruleName *" -ErrorAction SilentlyContinue |
    Where-Object { $_.Enabled -eq "True" -and $_.Action -eq "Block" })
if ($rules.Count -lt $paths.Count) { throw "The Siligent Docker egress policy is incomplete." }
Write-Host "[network-policy] Docker public-internet block rules are present."
