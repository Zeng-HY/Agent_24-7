param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$remoteRoot = $PSScriptRoot
$remotePython = Join-Path $remoteRoot '.venv\Scripts\pythonw.exe'
$remoteLauncher = Join-Path $remoteRoot 'autostart.py'
$remoteStartup = [Environment]::GetFolderPath('Startup')
$remoteLink = Join-Path $remoteStartup 'Agent Remote.lnk'
$remoteShell = New-Object -ComObject WScript.Shell
function Test-RemoteOurs($remotePath) {
    $remoteExisting = $remoteShell.CreateShortcut($remotePath)
    return $remoteExisting.Arguments -eq ('"' + $remoteLauncher + '"')
}
if ($Disable) {
    if (Test-Path -LiteralPath $remoteLink) {
        if (-not (Test-RemoteOurs $remoteLink)) { throw 'Startup shortcut belongs to another launcher; not removed.' }
        Remove-Item -LiteralPath $remoteLink
    }
    Write-Output 'Login auto-start disabled. The running service was not stopped.'
    exit
}
if (-not (Test-Path -LiteralPath $remotePython) -or -not (Test-Path -LiteralPath $remoteLauncher)) { throw 'Remote launcher or Python environment is missing.' }
if ((Test-Path -LiteralPath $remoteLink) -and -not (Test-RemoteOurs $remoteLink)) { throw 'Startup shortcut already exists for another launcher; not overwritten.' }
$remoteShortcut = $remoteShell.CreateShortcut($remoteLink)
$remoteShortcut.TargetPath = $remotePython
$remoteShortcut.Arguments = '"' + $remoteLauncher + '"'
$remoteShortcut.WorkingDirectory = $remoteRoot
$remoteShortcut.Description = 'Start the phone remote website after Windows login; reuse an existing service.'
$remoteShortcut.WindowStyle = 7
$remoteShortcut.Save()
Write-Output 'Current-user login auto-start installed. No administrator password is required.'
