param([Parameter(Mandatory=$true)][string]$InnoCompiler, [string]$Python = '.venv\Scripts\python.exe')
$ErrorActionPreference = 'Stop'
$buildRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $buildRoot
& $Python deploy/windows/version.py
if ($LASTEXITCODE -ne 0) { throw 'Version preparation failed' }
& $Python -m PyInstaller --noconfirm --clean 'deploy\windows\AgentRemote.spec'
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
& $InnoCompiler 'deploy\windows\setup.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
& $Python deploy/windows/version.py --manifest
if ($LASTEXITCODE -ne 0) { throw 'Update manifest failed' }
$version = Get-Content windows-version.json -Raw | ConvertFrom-Json
Get-FileHash ("dist\AgentRemote-"+$version.version+"-Setup.exe") -Algorithm SHA256
