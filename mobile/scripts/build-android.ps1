param([string]$JavaHome, [string]$AndroidSdk)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!$JavaHome) {
    $localJdk = Get-ChildItem .toolchain/jdk -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
    $JavaHome = if ($localJdk) { $localJdk.FullName } else { $env:JAVA_HOME }
}
if (!$AndroidSdk) {
    $AndroidSdk = if (Test-Path .toolchain/sdk) { (Resolve-Path .toolchain/sdk).Path } else { $env:ANDROID_HOME }
}
if (!$JavaHome -or !$AndroidSdk) { throw 'Provide Java 21 -JavaHome and installed SDK 36 -AndroidSdk.' }
$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidSdk
$env:GRADLE_USER_HOME = Join-Path (Get-Location) '.toolchain/gradle'
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed: $LASTEXITCODE" }
}
Invoke-Checked 'npm.cmd' @('ci')
Invoke-Checked 'npm.cmd' @('test')
Invoke-Checked 'npm.cmd' @('run', 'check:ci')
Invoke-Checked 'npm.cmd' @('run', 'build')
if (!(Test-Path android)) { Invoke-Checked 'npx.cmd' @('cap', 'add', 'android') }
Invoke-Checked 'npx.cmd' @('cap', 'sync', 'android')
Invoke-Checked 'node' @('scripts/prepare-android.mjs')
Push-Location android
try { Invoke-Checked '.\gradlew.bat' @('--no-daemon', '--console=plain', 'assembleDebug') }
finally { Pop-Location }
New-Item -ItemType Directory -Force build | Out-Null
Copy-Item android/app/build/outputs/apk/debug/app-debug.apk build/PocketAgentDesk-debug.apk -Force
Invoke-Checked "$AndroidSdk/build-tools/36.0.0/apksigner.bat" @('verify', '--verbose', '--print-certs', 'build/PocketAgentDesk-debug.apk')
Get-FileHash build/PocketAgentDesk-debug.apk -Algorithm SHA256
