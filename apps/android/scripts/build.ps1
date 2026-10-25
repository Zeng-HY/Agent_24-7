param([string[]]$Tasks = @("assembleDebug", "testDebugUnitTest", "lintDebug", "assembleDebugAndroidTest"))
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$repo = Resolve-Path (Join-Path $root "../..")
$chain = Join-Path $repo "mobile/.toolchain"
$env:JAVA_HOME = if ($env:STUDIO_GRADLE_JDK) { $env:STUDIO_GRADLE_JDK } else { Join-Path $chain "jdk/jdk-21.0.12.1+1" }
$env:PATH = "$env:JAVA_HOME/bin;" + $env:PATH
if (!$env:ANDROID_HOME) { $env:ANDROID_HOME = Join-Path $chain "sdk" }
if (!$env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME = Join-Path $chain "gradle" }
$sdkProperty = $env:ANDROID_HOME.Replace("\", "/").Replace(":", "\:")
Set-Content -LiteralPath (Join-Path $root "local.properties") -Value "sdk.dir=$sdkProperty" -Encoding ascii
# 0.8: signed with this computer's Android debug key, as the old app (mobile/) is. It is not created here: a new key
# would make every installed copy refuse the next update.
$userHome = if ($env:ANDROID_USER_HOME) { $env:ANDROID_USER_HOME } else { Join-Path $HOME ".android" }
if (!(Test-Path -LiteralPath (Join-Path $userHome "debug.keystore"))) { throw "No debug.keystore in $userHome. Build on the computer that signs the old app." }
# Environment changes belong to this process only. No global JAVA_HOME / PATH changes.
Push-Location $root
try { & ./gradlew.bat @Tasks --console=plain; if ($LASTEXITCODE -ne 0) { throw "Gradle failed ($LASTEXITCODE)" } } finally { Pop-Location }
