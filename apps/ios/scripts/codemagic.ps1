<#
.SYNOPSIS
  Starts a Codemagic workflow for the native iOS app, waits for it and downloads its artifacts.

.DESCRIPTION
  Reads the Codemagic API token from %USERPROFILE%\.codemagic\token.txt (never kept in the repo, never
  printed). The branch must already be pushed: Codemagic builds what is on GitHub.

.EXAMPLE
  ./codemagic.ps1 -ListApps
  ./codemagic.ps1 -AppId <id> -Workflow ios-native-check -Mode shots
  ./codemagic.ps1 -AppId <id> -Workflow ios-native-check -Mode shots -Only "testLight testLargestText"
  ./codemagic.ps1 -AppId <id> -Workflow ios-native-testflight
  ./codemagic.ps1 -BuildId <id>        # follow a build already started, then download as above
#>
param(
    [ValidateSet('ios-native-check', 'ios-native-testflight')]
    [string]$Workflow = 'ios-native-check',
    [ValidateSet('compile', 'shots')]
    [string]$Mode = 'compile',
    [string]$Runtimes = '',
    # Some of the tour's variants only (testLight, testDark, testLargestText), space-separated.
    [string]$Only = '',
    [string]$Branch = 'main',
    [string]$AppId = $env:TELEPLY_CODEMAGIC_APP,
    [string]$OutDir = (Join-Path $PSScriptRoot '..\build\codemagic'),
    [string]$BuildId = '',
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
if ($BuildId) {
    $buildId = $BuildId
    Write-Host "Following build $buildId"
} else {
    if (-not $AppId) { throw 'Pass -AppId (see -ListApps) or set TELEPLY_CODEMAGIC_APP' }
    $variables = @{ CHECK_MODE = $Mode }
    if ($Runtimes) { $variables.SHOT_RUNTIMES = $Runtimes }
    if ($Only) { $variables.SHOT_ONLY = $Only }
    $body = @{ appId = $AppId; workflowId = $Workflow; branch = $Branch; environment = @{ variables = $variables } } |
        ConvertTo-Json -Depth 5
    $buildId = (Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' -Body $body "$api/builds").buildId
    Write-Host "Started $Workflow ($Mode) on ${Branch}: build $buildId"
}

$finished = 'finished', 'failed', 'canceled', 'timeout', 'skipped', 'warning'
$started = Get-Date
$misses = 0
$build = $null
do {
    Start-Sleep -Seconds 30
    # A dropped connection now and then is no reason to stop following the build (10-26: EOF from the API).
    try {
        $build = (Invoke-RestMethod -Headers $headers "$api/builds/$buildId").build
        $misses = 0
    } catch {
        $misses++
        Write-Host ('{0:mm\:ss}  (no answer from Codemagic, try {1}: {2})' -f ((Get-Date) - $started), $misses, $_.Exception.Message)
        if ($misses -ge 10) { throw }
        continue
    }
    Write-Host ('{0:mm\:ss}  {1}' -f ((Get-Date) - $started), $build.status)
} while (-not $build -or $build.status -notin $finished)

$target = Join-Path $OutDir $buildId
New-Item -ItemType Directory -Force $target | Out-Null
# The API spells it "artefacts"; the zip holds every path listed under artifacts in codemagic.yaml.
foreach ($artifact in @($build.artefacts)) {
    $file = Join-Path $target $artifact.name
    Invoke-WebRequest -Headers $headers -Uri $artifact.url -OutFile $file
    Write-Host "Downloaded $($artifact.name)"
    if ($file -like '*.zip') { Expand-Archive -Force -Path $file -DestinationPath (Join-Path $target 'artefacts') }
}

# Each step's status and log (a script step keeps its log on its subaction), readable without the website.
$step = 0
foreach ($action in @($build.buildActions)) {
    $step++
    Write-Host ('step {0:00} {1,-10} {2}' -f $step, $action.status, $action.name)
    $urls = @($action.logUrl) + @($action.subactions | ForEach-Object { $_.logUrl }) | Where-Object { $_ }
    $part = 0
    foreach ($url in $urls) {
        $part++
        $name = ($action.name -replace '[^\w\-]+', '-').Trim('-')
        $file = Join-Path $target ('{0:00}-{1}-{2}.log' -f $step, $part, $name)
        try {
            Invoke-WebRequest -Headers $headers -Uri $url -OutFile $file
            # Plain text: the logs come as HTML-coloured lines.
            (Get-Content $file) -replace '<[^>]+>', '' -replace '&gt;', '>' -replace '&lt;', '<' -replace '&amp;', '&' -replace '&quot;', '"' -replace '&#39;', "'" |
                Set-Content $file -Encoding utf8
        } catch { Write-Host "  (log not downloaded: $($_.Exception.Message))" }
    }
}
if ($build.message) { Write-Host "Message: $($build.message)" }
Write-Host "Build $buildId $($build.status) after $([int]((Get-Date) - $started).TotalMinutes) min; artifacts in $target"
if ($build.status -ne 'finished') { exit 1 }
