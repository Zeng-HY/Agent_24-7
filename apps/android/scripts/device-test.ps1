param([Parameter(Mandatory=$true)][string]$Serial, [switch]$InstrumentationOnly)
$ErrorActionPreference="Stop"
$root=Split-Path $PSScriptRoot -Parent
$repo=Resolve-Path (Join-Path $root "../..")
$chain=Join-Path $repo "mobile/.toolchain"
if(!$env:ANDROID_HOME) { $env:ANDROID_HOME=Join-Path $chain "sdk" }
$adb=Join-Path $env:ANDROID_HOME "platform-tools/adb.exe"
$env:JAVA_HOME=if($env:STUDIO_GRADLE_JDK) { $env:STUDIO_GRADLE_JDK } else { Join-Path $chain "jdk/jdk-21.0.12.1+1" }
$env:PATH="$env:JAVA_HOME/bin;$(Join-Path $env:ANDROID_HOME 'platform-tools');"+$env:PATH
$env:ANDROID_SERIAL=$Serial
$taskDataRoot=Split-Path $env:ANDROID_HOME -Parent
$taskJavaHome=(Join-Path $taskDataRoot "user-home").Replace("\", "/")
$taskTemp=(Join-Path $taskDataRoot "temp").Replace("\", "/")
New-Item -ItemType Directory -Force $taskJavaHome,$taskTemp | Out-Null
$env:JAVA_TOOL_OPTIONS="$env:JAVA_TOOL_OPTIONS -Duser.home=$taskJavaHome -Djava.io.tmpdir=$taskTemp".Trim()
$env:MAESTRO_CLI_NO_ANALYTICS="1"
$env:MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED="true"
$state=& $adb -s $Serial get-state
if($LASTEXITCODE -ne 0 -or $state.Trim() -ne "device") { throw "Selected device is not connected/authorized" }
# Explicitly selected serial; only installs the development copy (0.8: .dev, beside the app, never its data) and its tests.
& $adb -s $Serial install -r (Join-Path $root "app/build/outputs/apk/debug/app-debug.apk")
if($LASTEXITCODE -ne 0) { throw "Preview installation failed" }
$launch=& $adb -s $Serial shell am start -W -n com.pocketagentdesk.remote.nativepreview.dev/com.pocketagentdesk.nativepreview.MainActivity
$launch
if($LASTEXITCODE -ne 0 -or ($launch -join "`n") -notmatch "Status: ok") { throw "Preview launch was not confirmed" }
Write-Output "Old package presence (absence is allowed):"
& $adb -s $Serial shell pm path com.pocketagentdesk.remote
& $adb -s $Serial install -r (Join-Path $root "app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk")
if($LASTEXITCODE -ne 0) { throw "Instrumentation installation failed" }
$instrument=& $adb -s $Serial shell am instrument -w com.pocketagentdesk.remote.nativepreview.dev.test/androidx.test.runner.AndroidJUnitRunner
$instrument
if(($instrument -join "`n") -notmatch 'OK \(\d+ tests?\)') { throw "Instrumentation tests did not pass" }
if(!$InstrumentationOnly) {
    $maestro=Join-Path $chain "maestro-2.11.0/maestro/bin/maestro.bat"
    if(!(Test-Path $maestro)) { throw "Install pinned Maestro 2.11.0 as documented in README" }
    Push-Location $root
    try {
        # This fixture run resets ONLY the development copy's data; the app and its login are another package.
        & $maestro --udid $Serial test maestro/fixture.yaml
        if($LASTEXITCODE -ne 0) { throw "Maestro fixture failed" }
    } finally { Pop-Location }
}
