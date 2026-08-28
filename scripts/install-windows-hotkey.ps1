<#
.SYNOPSIS
    Register a Windows hotkey that captures the clipboard into melt.

.DESCRIPTION
    Creates a Start Menu shortcut that runs the capture helper without a console
    window. Windows only honours a shortcut's hotkey when the shortcut lives in
    the Start Menu or on the Desktop, so the shortcut is always written there.
    Running this again overwrites the existing shortcut.

.EXAMPLE
    .\scripts\install-windows-hotkey.ps1

.EXAMPLE
    .\scripts\install-windows-hotkey.ps1 -Hotkey "CTRL+ALT+K"

.EXAMPLE
    .\scripts\install-windows-hotkey.ps1 -Remove
#>
param(
    [string]$Hotkey = "CTRL+ALT+M",
    [string]$Name = "melt capture",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LinkPath = Join-Path ([Environment]::GetFolderPath("Programs")) "$Name.lnk"

if ($Remove) {
    if (Test-Path $LinkPath) {
        Remove-Item $LinkPath
        Write-Host "removed: $LinkPath"
    } else {
        Write-Host "already removed: $LinkPath"
    }
    return
}

$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) {
    $Pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
}
if (-not $Pythonw) {
    throw @"
No pythonw.exe found. Create the virtual environment first:
  python -m venv .venv
"@
}

$Helper = Join-Path $Root "scripts\melt-capture"
if (-not (Test-Path $Helper)) {
    throw "Capture helper not found: $Helper"
}
if (-not (Test-Path (Join-Path $Root ".env"))) {
    throw @"
No .env found in $Root. Create it and set MELT_TOKEN:
  Copy-Item .env.example .env
"@
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($LinkPath)
$link.TargetPath = $Pythonw
$link.Arguments = "`"$Helper`""
$link.WorkingDirectory = $Root
$link.Description = "Capture the clipboard into melt"
$link.WindowStyle = 7
$link.Hotkey = $Hotkey
$link.Save()

Write-Host "shortcut: $LinkPath"
Write-Host "hotkey: $Hotkey"
Write-Host "runs: $Pythonw `"$Helper`""
Write-Host ""
Write-Host "Copy some text, then press $Hotkey. Check http://127.0.0.1:8080"
