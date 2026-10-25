# Builds the release APK for in-app updates: build/Teleply-<version>-<code>.apk, signed with the app's own key (1.0).
# Publishing stays a manual step: attach the file to a GitHub Release of Zeng-HY/Agent_24-7 (see README).
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
# The certificate of ~/.android/teleply-signing/release.p12. Phones take an update only with this very key.
$expected = "1df09ab72fd7e3e1c9f57569d2050ae1db933148d1d5fbb7517a28edb2e22946"
& (Join-Path $PSScriptRoot "build.ps1") -Tasks @("testDebugUnitTest", "assembleRelease")
$meta = Get-Content (Join-Path $root "app/build/outputs/apk/release/output-metadata.json") -Raw | ConvertFrom-Json
$element = $meta.elements[0]
$version = $element.versionName
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Unexpected version name $($element.versionName)" }
New-Item -ItemType Directory -Force (Join-Path $root "build") | Out-Null
$output = Join-Path $root "build/Teleply-$version-$($element.versionCode).apk"
Copy-Item (Join-Path $root "app/build/outputs/apk/release/$($element.outputFile)") $output -Force
$tools = Get-ChildItem (Join-Path $env:ANDROID_HOME "build-tools") -Directory | Sort-Object Name | Select-Object -Last 1
$certs = & (Join-Path $tools.FullName "apksigner.bat") verify --print-certs $output
if ($LASTEXITCODE -ne 0) { throw "Signature check failed" }
$certs
if (($certs -join "`n") -notmatch "certificate SHA-256 digest: $expected") { throw "Signed with another key, not the app's release key" }
Get-FileHash $output -Algorithm SHA256
