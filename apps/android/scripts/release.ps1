# Builds the release APK for in-app updates: build/TeleplyNative-<version>-<code>.apk, signed with the shared key.
# Publishing stays a manual step: attach the file to a GitHub Release of Zeng-HY/Agent_24-7 (see README).
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot "build.ps1") -Tasks @("testDebugUnitTest", "assembleRelease")
$meta = Get-Content (Join-Path $root "app/build/outputs/apk/release/output-metadata.json") -Raw | ConvertFrom-Json
$element = $meta.elements[0]
$version = ($element.versionName -split '-')[0]
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Unexpected version name $($element.versionName)" }
New-Item -ItemType Directory -Force (Join-Path $root "build") | Out-Null
$output = Join-Path $root "build/TeleplyNative-$version-$($element.versionCode).apk"
Copy-Item (Join-Path $root "app/build/outputs/apk/release/$($element.outputFile)") $output -Force
$tools = Get-ChildItem (Join-Path $env:ANDROID_HOME "build-tools") -Directory | Sort-Object Name | Select-Object -Last 1
& (Join-Path $tools.FullName "apksigner.bat") verify --print-certs $output
if ($LASTEXITCODE -ne 0) { throw "Signature check failed" }
Get-FileHash $output -Algorithm SHA256
