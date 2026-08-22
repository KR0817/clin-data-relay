[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$UseCachedImages,
    [int]$TimeoutSeconds = 240
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sandboxDirectory = Join-Path $projectRoot 'infrastructure\libreclinica'
$environmentFile = Join-Path $sandboxDirectory '.env.sandbox'
$composeFile = Join-Path $sandboxDirectory 'compose.sandbox.yaml'
$lockFile = Join-Path $sandboxDirectory 'upstream.lock.md'
$releaseWarPath = Join-Path $sandboxDirectory 'artifacts\LibreClinica-web-1.4.0.war'
$releaseWarSha256 = '25378635ab396195d2bc8d58ee2988383fccf0699d2c5222800c8a37524179c7'
$wsWarPath = Join-Path $sandboxDirectory 'artifacts\LibreClinica-ws-1.4.0rc1.war'
$wsWarSha256 = '1f57e077d30f39b2f6c7b584ddd405420b3a990d33773fdb122019c0a8083487'

function Stop-WithMessage([string]$Message) {
    Write-Error $Message
    exit 1
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) {
    $dockerDefaultPath = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $dockerDefaultPath) {
        $dockerCommand = Get-Item -LiteralPath $dockerDefaultPath
    }
}
if (-not $dockerCommand) {
    Stop-WithMessage 'BLOCK: Docker Desktop is not installed or not available on PATH. Install and start Docker Desktop, then rerun this script.'
}
$dockerExecutable = $dockerCommand.Source
if ([string]::IsNullOrWhiteSpace($dockerExecutable)) {
    $dockerExecutable = $dockerCommand.FullName
}
$dockerToolsDirectory = Split-Path -Parent $dockerExecutable
if (($env:Path -split ';') -notcontains $dockerToolsDirectory) {
    $env:Path = "$env:Path;$dockerToolsDirectory"
}

if (-not (Test-Path -LiteralPath $environmentFile)) {
    Stop-WithMessage "BLOCK: Missing $environmentFile. Copy .env.sandbox.example to .env.sandbox."
}

$environmentEntries = Get-Content -LiteralPath $environmentFile | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' }
$environment = @{}
foreach ($entry in $environmentEntries) {
    $name, $value = $entry -split '=', 2
    $environment[$name] = $value
}

if (-not (Test-Path -LiteralPath $releaseWarPath)) {
    Stop-WithMessage "BLOCK: Missing official LibreClinica 1.4.0 WAR. Run .\\scripts\\fetch_libreclinica_release.ps1, then retry."
}
$actualReleaseWarSha256 = (Get-FileHash -LiteralPath $releaseWarPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualReleaseWarSha256 -ne $releaseWarSha256) {
    Stop-WithMessage "BLOCK: LibreClinica release WAR SHA-256 mismatch. Review $lockFile before proceeding."
}
if (-not (Test-Path -LiteralPath $wsWarPath)) {
    Stop-WithMessage "BLOCK: Missing official LibreClinica SOAP/ODM WAR. Review $lockFile, then download the pinned artifact."
}
$actualWsWarSha256 = (Get-FileHash -LiteralPath $wsWarPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualWsWarSha256 -ne $wsWarSha256) {
    Stop-WithMessage "BLOCK: LibreClinica SOAP/ODM WAR SHA-256 mismatch. Review $lockFile before proceeding."
}

& $dockerExecutable version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage 'BLOCK: Docker Desktop is installed but its engine is not running.'
}

& $dockerExecutable compose --env-file $environmentFile -f $composeFile config --quiet
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage 'BLOCK: Docker Compose configuration is invalid.'
}

Write-Output 'PASS: Docker Compose configuration is valid for the checksum-verified official LibreClinica 1.4.0 release WAR.'
if (-not $Start) {
    Write-Output 'NOT RUN: Container start was not requested. Use -Start for the synthetic sandbox only.'
    exit 0
}

if ($UseCachedImages) {
    & $dockerExecutable compose --env-file $environmentFile -f $composeFile up --detach --no-build
} else {
    & $dockerExecutable compose --env-file $environmentFile -f $composeFile up --build --detach
}
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage 'BLOCK: Docker Compose could not start the synthetic LibreClinica sandbox.'
}

$hostPort = if ($environment.ContainsKey('LIBRECLINICA_HOST_PORT')) { $environment['LIBRECLINICA_HOST_PORT'] } else { '8081' }
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$endpoint = "http://127.0.0.1:$hostPort/"
$protectedEndpoint = "http://127.0.0.1:$hostPort/LibreClinica/MainMenu"
$dataWsdlEndpoint = "http://127.0.0.1:$hostPort/LibreClinica-ws/ws/dataWsdl.wsdl"
do {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $endpoint -TimeoutSec 5
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            $protectedRequest = [System.Net.HttpWebRequest]::Create($protectedEndpoint)
            $protectedRequest.AllowAutoRedirect = $false
            $protectedRequest.Method = 'GET'
            $protectedResponse = $protectedRequest.GetResponse()
            try {
                $protectedStatus = [int]$protectedResponse.StatusCode
                $protectedLocation = $protectedResponse.Headers['Location']
            } finally {
                $protectedResponse.Close()
            }
            if ($protectedStatus -lt 300 -or $protectedStatus -ge 400 -or [string]::IsNullOrWhiteSpace($protectedLocation) -or $protectedLocation -notmatch '/LibreClinica/pages/login/login') {
                Stop-WithMessage "BLOCK: LibreClinica root responded, but the protected main menu did not redirect to the login route. Status: $protectedStatus; Location: $protectedLocation"
            }
            $dataWsdlResponse = Invoke-WebRequest -UseBasicParsing -Uri $dataWsdlEndpoint -TimeoutSec 5
            if ($dataWsdlResponse.StatusCode -ne 200 -or $dataWsdlResponse.Content -notmatch 'importRequest') {
                Stop-WithMessage "BLOCK: LibreClinica SOAP/ODM data WSDL is unavailable or does not expose importRequest."
            }
            Write-Output "PASS: LibreClinica synthetic sandbox responded at $endpoint (HTTP $($response.StatusCode))."
            Write-Output "PASS: Protected main menu redirected to the local login route (HTTP $protectedStatus)."
            Write-Output "PASS: SOAP/ODM data import WSDL responded at $dataWsdlEndpoint (HTTP $($dataWsdlResponse.StatusCode))."
            & $dockerExecutable compose --env-file $environmentFile -f $composeFile ps
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 5
    }
} while ((Get-Date) -lt $deadline)

& $dockerExecutable compose --env-file $environmentFile -f $composeFile ps
Stop-WithMessage "BLOCK: LibreClinica did not respond at $endpoint within $TimeoutSeconds seconds. Inspect the Docker Compose logs; do not load clinical data."
