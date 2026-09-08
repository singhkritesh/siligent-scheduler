[CmdletBinding()]
param([switch]$SkipEgress)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Scheduler.Common.ps1")
$arguments = @("./verify.sh")
if ($SkipEgress) { $arguments += "--skip-egress" }
Invoke-SchedulerBash -Arguments $arguments
