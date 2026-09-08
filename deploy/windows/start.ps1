[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Scheduler.Common.ps1")
Invoke-SchedulerBash -Arguments @("./start.sh")
