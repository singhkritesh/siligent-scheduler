Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-SchedulerRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-GitBash {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Git\bin\bash.exe"),
        (Join-Path $env:ProgramFiles "Git\usr\bin\bash.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Git\bin\bash.exe")
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and
            (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return $candidate
        }
    }
    $command = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    throw "Git for Windows Bash is required. Run preflight.ps1 -InstallMissing."
}

function Convert-ToGitBashPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($resolved -notmatch '^([A-Za-z]):\\(.*)$') {
        throw "Expected a local Windows path: $resolved"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $rest = $Matches[2].Replace('\', '/')
    return "/$drive/$rest"
}

function Invoke-SchedulerBash {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $bash = Get-GitBash
    $root = Convert-ToGitBashPath -Path (Get-SchedulerRoot)
    foreach ($argument in $Arguments) {
        if ($argument -notmatch '^[A-Za-z0-9_./-]+$') {
            throw "Unsafe Bash wrapper argument: $argument"
        }
    }
    $command = "cd '$root' && " + ($Arguments -join " ")
    & $bash -lc $command
    if ($LASTEXITCODE -ne 0) {
        throw "Scheduler command failed with exit code $LASTEXITCODE."
    }
}

function Assert-SchedulerAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this operation from an Administrator PowerShell window."
    }
}
