<#
.SYNOPSIS
  Starts a Codemagic workflow for the native iOS app, waits for it and downloads its artifacts.

.DESCRIPTION
  Reads the Codemagic API token from %USERPROFILE%\.codemagic\token.txt (never kept in the repo, never
  printed). The branch must already be pushed: Codemagic builds what is on GitHub.

.EXAMPLE
  ./codemagic.ps1 -ListApps
  ./codemagic.ps1 -AppId <id> -Workflow ios-native-check -Mode shots
  ./codemagic.ps1 -AppId <id> -Workflow ios-native-testflight
#>
param(
    [ValidateSet('ios-native-check', 'ios-native-testflight')]
    [string]$Workflow = 'ios-native-check',
    [ValidateSet('compile', 'shots')]
    [string]$Mode = 'compile',
    [string]$Runtimes = '',
    [string]$Branch = 'ios-native',
    [string]$AppId = $env:TELEPLY_CODEMAGIC_APP,
    [string]$OutDir = (Join-Path $PSScriptRoot '..\build\codemagic'),
    [switch]$ListApps
)
$ErrorActionPreference = 'Stop'
$api = 'https://api.codemagic.io'
$tokenFile = Join-Path $env:USERPROFILE '.codemagic\token.txt'
if (-not (Test-Path $tokenFile)) { throw "No Codemagic token at $tokenFile" }
$headers = @{ 'x-auth-token' = (Get-Content -Raw $tokenFile).Trim() }

if ($ListApps) {
    (Invoke-RestMethod -Headers $headers "$api/apps").applications |
        ForEach-Object { [pscustomobject]@{ id = $_._id; name = $_.appName; repository = $_.repository.htmlUrl } } |
        Format-Table -AutoSize
    return
}
if (-not $AppId) { throw 'Pass -AppId (see -ListApps) or set TELEPLY_CODEMAGIC_APP' }

$variables = @{ CHECK_MODE = $Mode }
if ($Runtimes) { $variables.SHOT_RUNTIMES = $Runtimes }
$body = @{ appId = $AppId; workflowId = $Workflow; branch = $Branch; environment = @{ variables = $variables } } |
    ConvertTo-Json -Depth 5
$buildId = (Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' -Body $body "$api/builds").buildId
Write-Host "Started $Workflow ($Mode) on ${Branch}: build $buildId"

$finished = 'finished', 'failed', 'canceled', 'timeout', 'skipped', 'warning'
$started = Get-Date
do {
    Start-Sleep -Seconds 30
    $build = (Invoke-RestMethod -Headers $headers "$api/builds/$buildId").build
    Write-Host ('{0:mm\:ss}  {1}' -f ((Get-Date) - $started), $build.status)
} while ($build.status -notin $finished)

$target = Join-Path $OutDir $buildId
New-Item -ItemType Directory -Force $target | Out-Null
foreach ($artifact in $build.artifacts) {
    $file = Join-Path $target $artifact.name
    Invoke-WebRequest -Headers $headers -Uri $artifact.url -OutFile $file
    Write-Host "Downloaded $($artifact.name)"
}

# Each step's status, and its log when the API offers one, so a failure can be read without the website.
$step = 0
foreach ($action in @($build.buildActions)) {
    $step++
    Write-Host ('step {0:00} {1,-10} {2}' -f $step, $action.status, $action.name)
    if ($action.logUrl) {
        $name = ($action.name -replace '[^\w\-]+', '-').Trim('-')
        try { Invoke-WebRequest -Headers $headers -Uri $action.logUrl -OutFile (Join-Path $target ('{0:00}-{1}.log' -f $step, $name)) }
        catch { Write-Host "  (log not downloaded: $($_.Exception.Message))" }
    }
}
Write-Host "Build $buildId $($build.status) after $([int]((Get-Date) - $started).TotalMinutes) min; artifacts in $target"
if ($build.status -ne 'finished') { exit 1 }
