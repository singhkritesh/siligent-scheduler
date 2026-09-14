param(
    [Parameter(Mandatory = $true)][string]$Launcher,
    [string]$WslDistribution = "",
    [string]$WslLauncher = "",
    [string]$WslRoot = ""
)

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Siligent Scheduler.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)

if ($WslDistribution -and $WslLauncher -and $WslRoot) {
    if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
        throw "The Windows launcher file does not exist: $Launcher"
    }
    $wsl = Join-Path $env:SystemRoot "System32\wsl.exe"
    & $wsl -d $WslDistribution -- test -f $WslLauncher
    if ($LASTEXITCODE -ne 0) {
        throw "The WSL launcher file does not exist in distribution $WslDistribution: $WslLauncher"
    }
    $safeWslRoot = "'" + $WslRoot.Replace("'", "'`"'`"'") + "'"
    $shortcut.TargetPath = Join-Path $env:SystemRoot "System32\wsl.exe"
    $shortcut.Arguments = "-d `"$WslDistribution`" -- bash -lc `"cd $safeWslRoot && exec ./scripts/launch_ui.sh`""
} else {
    if ($WslDistribution -or $WslLauncher -or $WslRoot) {
        throw "WSL launcher configuration is incomplete."
    }
    $bash = (Get-Command bash.exe -ErrorAction Stop).Source
    $shortcut.TargetPath = $bash
    $shortcut.Arguments = "`"$Launcher`""
}

$shortcut.WorkingDirectory = Split-Path $Launcher
$shortcut.Description = "Start the local Siligent Scheduler"
$shortcut.Save()
Write-Output "[launcher-install] Desktop shortcut: $shortcutPath"
