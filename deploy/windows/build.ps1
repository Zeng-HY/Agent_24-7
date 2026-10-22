param([Parameter(Mandatory=$true)][string]$InnoCompiler)
$ErrorActionPreference = 'Stop'
$buildRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $buildRoot
& '.venv\Scripts\python.exe' -m PyInstaller --noconfirm --clean 'deploy\windows\AgentRemote.spec'
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
& $InnoCompiler 'deploy\windows\setup.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Get-FileHash 'dist\AgentRemote-0.27.0-dev-Setup.exe' -Algorithm SHA256
