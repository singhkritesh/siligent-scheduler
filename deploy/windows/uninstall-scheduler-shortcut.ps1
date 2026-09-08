Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Siligent Scheduler.lnk"
if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    Write-Host "[uninstall] Siligent Scheduler desktop shortcut is not present."
    exit 0
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ($shortcut.Description -ne "Start the local Siligent Scheduler") {
    throw "Refusing to remove an unrecognized shortcut at $shortcutPath"
}
Remove-Item -LiteralPath $shortcutPath -Force
Write-Host "[uninstall] Removed desktop shortcut: $shortcutPath"
