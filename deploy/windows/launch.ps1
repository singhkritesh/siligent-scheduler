[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Scheduler.Common.ps1")
Invoke-SchedulerBash -Arguments @("./start.sh")
$root = Get-SchedulerRoot
$envPath = Join-Path $root ".env"
$port = 8443
if (Test-Path -LiteralPath $envPath) {
    $line = Get-Content -LiteralPath $envPath |
        Where-Object { $_ -match '^UI_PORT=(\d+)$' } | Select-Object -First 1
    if ($null -ne $line) { $port = [int]([regex]::Match($line, '(\d+)').Value) }
}
Start-Process "https://127.0.0.1:$port"
