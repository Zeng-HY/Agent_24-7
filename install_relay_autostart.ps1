param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$relayRoot = $PSScriptRoot
$relayConfig = Join-Path $relayRoot 'attachments\relay-device\device.json'
$relayPython = Join-Path $relayRoot '.venv\Scripts\pythonw.exe'
$relayLauncher = Join-Path $relayRoot 'relay_supervisor.py'
$relayLink = Join-Path ([Environment]::GetFolderPath('Startup')) 'Agent Remote Relay.lnk'
$relayShell = New-Object -ComObject WScript.Shell
$relayArgs = '"' + $relayLauncher + '"'
if (Test-Path -LiteralPath $relayLink) {
    if ($relayShell.CreateShortcut($relayLink).Arguments -ne $relayArgs) { throw 'Existing shortcut belongs to another installation.' }
}
if ($Disable) {
    if (Test-Path -LiteralPath $relayLink) { Remove-Item -LiteralPath $relayLink }
    Write-Output 'Relay login startup disabled. Running processes were not stopped.'
    exit
}
if (-not (Test-Path -LiteralPath $relayConfig)) { throw 'Enroll this computer before enabling startup.' }
$relayData = Get-Content -LiteralPath $relayConfig -Raw -Encoding UTF8 | ConvertFrom-Json
if ($relayData.revoked -or -not (Test-Path -LiteralPath $relayData.frpc_executable)) { throw 'Active device configuration and frpc_executable are required.' }
$relayShortcut = $relayShell.CreateShortcut($relayLink)
$relayShortcut.TargetPath = $relayPython
$relayShortcut.Arguments = $relayArgs
$relayShortcut.WorkingDirectory = $relayRoot
$relayShortcut.WindowStyle = 7
$relayShortcut.Save()
Write-Output 'Relay startup enabled for this Windows login. It starts at next login.'
