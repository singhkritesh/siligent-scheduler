[CmdletBinding()]
param(
    [switch]$Offline,
    [switch]$Connected,
    [switch]$WithLocalModel,
    [switch]$WithoutLlm,
    [switch]$NoStart,
    [switch]$NoLauncher,
    [switch]$AllowUnsignedDevelopmentBundle,
    [switch]$Yes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Scheduler.Common.ps1")

if ($Offline -and $Connected) { throw "Choose Offline or Connected, not both." }
if ($WithLocalModel -and $WithoutLlm) { throw "Choose one intake profile." }
if ($Connected) {
    Assert-SchedulerAdministrator
    & (Join-Path $PSScriptRoot "preflight.ps1") -InstallMissing `
        -AcceptInstall:$Yes -WithLocalModel:$WithLocalModel
} else {
    & (Join-Path $PSScriptRoot "preflight.ps1")
}

$arguments = @("./install.sh")
if ($Offline) { $arguments += "--offline" }
if ($Connected) { $arguments += "--connected" }
if ($WithLocalModel) { $arguments += "--with-local-model" }
if ($WithoutLlm) { $arguments += "--without-llm" }
if ($NoStart) { $arguments += "--no-start" }
if ($NoLauncher) { $arguments += "--no-launcher" }
if ($AllowUnsignedDevelopmentBundle) { $arguments += "--allow-unsigned-development-bundle" }
if ($Yes) { $arguments += "--yes" }
Invoke-SchedulerBash -Arguments $arguments
