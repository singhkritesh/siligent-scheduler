[CmdletBinding()]
param(
    [switch]$InstallMissing,
    [switch]$AcceptInstall,
    [switch]$WithLocalModel
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Confirm-Install([string]$Message) {
    if ($AcceptInstall) { return }
    $answer = Read-Host "$Message [y/N]"
    if ($answer -notin @("y", "Y")) { throw "Installation was declined." }
}

function Install-WingetPackage([string]$Id, [string]$Label) {
    if (-not $InstallMissing) { throw "$Label is missing." }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "winget is required for connected Windows prerequisite installation."
    }
    Confirm-Install "Install $Label from its approved winget source?"
    & winget.exe install --exact --id $Id --accept-package-agreements `
        --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) { throw "Could not install $Label." }
}

$os = Get-CimInstance Win32_OperatingSystem
if ([int]$os.ProductType -ne 1 -or [version]$os.Version -lt [version]"10.0.19045") {
    throw "Windows 10 22H2 build 19045 or Windows 11 workstation is required."
}
if ($env:PROCESSOR_ARCHITECTURE -notin @("AMD64", "ARM64")) {
    throw "A 64-bit Windows host is required."
}
$memory = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
if ($memory -lt 4GB) { throw "At least 4 GB RAM is required; 8 GB or more is recommended." }

if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue) -and
    -not (Test-Path "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe")) {
    Install-WingetPackage -Id "Docker.DockerDesktop" -Label "Docker Desktop"
}
if (-not (Get-Command bash.exe -ErrorAction SilentlyContinue) -and
    -not (Test-Path "$env:ProgramFiles\Git\bin\bash.exe")) {
    Install-WingetPackage -Id "Git.Git" -Label "Git for Windows"
}
if ($WithLocalModel -and -not (Get-Command ollama.exe -ErrorAction SilentlyContinue)) {
    Install-WingetPackage -Id "Ollama.Ollama" -Label "Ollama"
}

$dockerPath = "$env:ProgramFiles\Docker\Docker\resources\bin"
if (Test-Path $dockerPath) { $env:Path = "$dockerPath;$env:Path" }
if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    throw "Docker was installed but is not yet available. Restart PowerShell and rerun install.ps1."
}
& docker.exe compose version *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 is unavailable." }

& docker.exe info *> $null
if ($LASTEXITCODE -ne 0) {
    $desktop = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) { Start-Process $desktop | Out-Null }
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        & docker.exe info *> $null
        if ($LASTEXITCODE -eq 0) { break }
    } while ((Get-Date) -lt $deadline)
    if ($LASTEXITCODE -ne 0) { throw "Docker Desktop did not become ready within three minutes." }
}

Write-Host "[preflight] Windows host, Docker, Compose, and shell prerequisites passed."
