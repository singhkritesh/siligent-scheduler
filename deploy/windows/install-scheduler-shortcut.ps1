param(
    [Parameter(Mandatory = $true)][string]$Launcher,
    [string]$WslDistribution = "",
    [string]$WslLauncher = ""
)

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Siligent Scheduler.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)

if ($WslDistribution -and $WslLauncher) {
    $shortcut.TargetPath = Join-Path $env:SystemRoot "System32\wsl.exe"
    $shortcut.Arguments = "-d `"$WslDistribution`" -- bash `"$WslLauncher`""
} else {
    $bash = (Get-Command bash.exe -ErrorAction Stop).Source
    $shortcut.TargetPath = $bash
    $shortcut.Arguments = "`"$Launcher`""
}

$shortcut.WorkingDirectory = Split-Path $Launcher
$shortcut.Description = "Start the local Siligent Scheduler"
$shortcut.Save()
Write-Output "[launcher-install] Desktop shortcut: $shortcutPath"
