[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$CompanionPort = 8000,
    [ValidateRange(1024, 65535)][int]$LibreClinicaHostPort = 8081,
    [ValidateRange(1024, 65535)][int]$MailHostPort = 1081,
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,62}$')][string]$ComposeProject = 'clinical-edc-portable',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$bundleRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$libreClinicaRoot = Join-Path $bundleRoot 'libreclinica'
$composePath = Join-Path $libreClinicaRoot 'compose.portable.yaml'
$assetManifestPath = Join-Path $libreClinicaRoot 'OFFLINE-ASSETS.sha256'
$imageArchivePath = Join-Path $libreClinicaRoot 'images\libreclinica-stack.tar'
$portableDataRoot = if ([string]::IsNullOrWhiteSpace($env:COMPANION_PORTABLE_DATA_ROOT)) {
    $bundleRoot
} else {
    [IO.Path]::GetFullPath($env:COMPANION_PORTABLE_DATA_ROOT)
}
$runtimeDirectory = Join-Path $portableDataRoot '.runtime'
$kimiCredentialPath = Join-Path $runtimeDirectory 'kimi-api-key.txt'
$libreClinicaCredentialPath = Join-Path $runtimeDirectory 'libreclinica-soap-credentials.json'
$executablePath = Join-Path $bundleRoot 'ClinicalEdcCompanion.exe'
$pidPath = Join-Path $runtimeDirectory 'companion.pid'
$hostPreflightPath = Join-Path $PSScriptRoot 'portable_host_preflight.ps1'
$hostDiagnosticPath = Join-Path $runtimeDirectory 'portable-host-diagnostic.json'

function Assert-BundleDescendant {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith("$bundleRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Asset path escaped the portable bundle: $resolved"
    }
    return $resolved
}

function Test-HttpReady {
    param([Parameter(Mandatory = $true)][string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $hostPreflightPath -PathType Leaf)) {
    throw "Required host preflight is missing: $hostPreflightPath"
}
. (Join-Path $PSScriptRoot 'portable_host_preflight.ps1')
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$initialHostState = Get-PortableHostState
$initialHostDiagnostic = Resolve-PortableHostDiagnostic -State $initialHostState
$dockerStartResult = $null
if ($initialHostDiagnostic.code -eq 'EDC-HOST-DOCKER-ENGINE-NOT-READY') {
    $dockerExecutable = Get-DockerExecutablePath
    Write-Output 'INFO: Docker Desktop is installed. Starting it and waiting for the Linux engine...'
    Write-Output 'INFO: If Docker shows its first-run agreement, accept it in the visible Docker Desktop window.'
    $dockerStartResult = Start-DockerDesktopAndWait -DockerExecutable $dockerExecutable
    if ($dockerStartResult.ready) {
        Write-Output "PASS: Docker Desktop Linux engine is ready (method: $($dockerStartResult.method))."
    }
}
Assert-PortableHostReady `
    -ReportPath $hostDiagnosticPath `
    -OpenDockerInstallPage `
    -DockerStartResult $dockerStartResult | Out-Null
$dockerExecutable = Get-DockerExecutablePath

foreach ($requiredPath in @($composePath, $assetManifestPath, $imageArchivePath, $executablePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required portable asset is missing: $requiredPath"
    }
}

foreach ($line in Get-Content -LiteralPath $assetManifestPath -Encoding UTF8) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
        throw "Invalid OFFLINE-ASSETS.sha256 entry: $line"
    }
    $expectedHash = $Matches[1]
    $assetPath = Assert-BundleDescendant -Path (Join-Path $libreClinicaRoot $Matches[2].Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $assetPath -PathType Leaf)) {
        throw "Verified offline asset is missing: $assetPath"
    }
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $assetPath).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Offline asset integrity check failed: $assetPath"
    }
}

$requiredImages = @(
    'clinical-edc-companion/libreclinica:1.4.0-sandbox',
    'postgres:16-alpine',
    'marlonb/mailcrab:v1.1.0'
)
$missingImage = $false
foreach ($image in $requiredImages) {
    $imageProbe = Invoke-PortableProcessQuiet `
        -FilePath $dockerExecutable `
        -ArgumentList @('image', 'inspect', $image)
    if ($imageProbe.exit_code -ne 0) { $missingImage = $true }
}
if ($missingImage) {
    & docker load --input $imageArchivePath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'docker load failed for the bundled LibreClinica stack.' }
}

if (-not (Test-Path -LiteralPath $kimiCredentialPath -PathType Leaf)) {
    & (Join-Path $PSScriptRoot 'configure_kimi.ps1') -RuntimeDirectory $runtimeDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Kimi first-run configuration failed.' }
}

$env:COMPOSE_PROJECT_NAME = $ComposeProject
$env:LIBRECLINICA_HOST_PORT = "$LibreClinicaHostPort"
$env:LIBRECLINICA_SMTP_HOST_PORT = "$MailHostPort"
$composeStart = Invoke-PortableProcessQuiet `
    -FilePath $dockerExecutable `
    -ArgumentList @('compose', '-p', $ComposeProject, '-f', $composePath, 'up', '-d')
if ($composeStart.exit_code -ne 0) { throw 'docker compose could not start LibreClinica.' }

$dbContainer = (& docker compose -p $ComposeProject -f $composePath ps -q db).Trim()
if ([string]::IsNullOrWhiteSpace($dbContainer)) {
    throw 'The portable PostgreSQL container was not created.'
}
$dbDeadline = (Get-Date).AddMinutes(2)
$databaseReady = $false
do {
    $databaseProbe = Invoke-PortableProcessQuiet `
        -FilePath $dockerExecutable `
        -ArgumentList @('exec', $dbContainer, 'pg_isready', '-U', 'clinica', '-d', 'libreclinica')
    if ($databaseProbe.exit_code -eq 0) { $databaseReady = $true; break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $dbDeadline)
if (-not $databaseReady) { throw 'Portable PostgreSQL did not become ready.' }

if (-not (Test-Path -LiteralPath $libreClinicaCredentialPath -PathType Leaf)) {
    & (Join-Path $PSScriptRoot 'configure_libreclinica.ps1') -DatabaseContainer $dbContainer -RuntimeDirectory $runtimeDirectory -GenerateLocalPassword
} else {
    & (Join-Path $PSScriptRoot 'configure_libreclinica.ps1') -DatabaseContainer $dbContainer -RuntimeDirectory $runtimeDirectory -ApplyExisting
}
if ($LASTEXITCODE -ne 0) { throw 'LibreClinica local-account configuration failed.' }

$loginUrl = "http://127.0.0.1:$LibreClinicaHostPort/LibreClinica/pages/login/login"
$wsdlUrl = "http://127.0.0.1:$LibreClinicaHostPort/LibreClinica-ws/ws/studySubject/v1/studySubjectWsdl.wsdl"
$webDeadline = (Get-Date).AddMinutes(5)
$webReady = $false
do {
    if ((Test-HttpReady -Url $loginUrl) -and (Test-HttpReady -Url $wsdlUrl)) { $webReady = $true; break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $webDeadline)
if (-not $webReady) {
    throw 'LibreClinica did not expose both the login page and SOAP WSDL within five minutes.'
}

$companionUrl = "http://127.0.0.1:$CompanionPort/"
$companionBrowserUrl = "${companionUrl}?ui=20260811-recognition-scope-v1"
$env:COMPANION_PORTABLE_LIBRECLINICA_BASE_URL = "http://127.0.0.1:$LibreClinicaHostPort"
if (-not (Test-HttpReady -Url "${companionUrl}api/health")) {
    $process = Start-Process -FilePath $executablePath -ArgumentList '--port', "$CompanionPort", '--no-browser' -WorkingDirectory $bundleRoot -PassThru
    [IO.File]::WriteAllText($pidPath, "$($process.Id)", (New-Object Text.UTF8Encoding($false)))
    $companionDeadline = (Get-Date).AddMinutes(2)
    do {
        if (Test-HttpReady -Url "${companionUrl}api/health") { break }
        if ($process.HasExited) { throw "ClinicalEdcCompanion.exe exited with code $($process.ExitCode)." }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $companionDeadline)
}
if (-not (Test-HttpReady -Url "${companionUrl}api/health")) {
    throw 'The companion did not become ready within two minutes.'
}

if (-not $NoBrowser) {
    Start-Process $companionBrowserUrl
    Start-Process $loginUrl
}
Write-Output "PASS: ClinData Relay: $companionUrl"
Write-Output "PASS: LibreClinica: $loginUrl"
Write-Output 'LibreClinica admin username: sandbox_admin'
