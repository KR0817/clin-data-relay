[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$artifactDirectory = Join-Path $projectRoot 'infrastructure\libreclinica\artifacts'
$artifactPath = Join-Path $artifactDirectory 'LibreClinica-web-1.4.0.war'
$temporaryArtifactPath = "$artifactPath.download"
$releaseUrl = 'https://www.libreclinica.org/downloads/LibreClinica-web-1.4.0.war'
$expectedSha256 = '25378635ab396195d2bc8d58ee2988383fccf0699d2c5222800c8a37524179c7'

function Stop-WithMessage([string]$Message) {
    Write-Error $Message
    exit 1
}

New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
if (Test-Path -LiteralPath $artifactPath) {
    $existingSha256 = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($existingSha256 -eq $expectedSha256) {
        Write-Output "PASS: Official LibreClinica 1.4.0 WAR is already present and SHA-256 verified: $artifactPath"
        exit 0
    }
    Stop-WithMessage "BLOCK: Existing release artifact SHA-256 does not match the official 1.4.0 value. Preserve it for investigation and do not overwrite it automatically: $artifactPath"
}

if (Test-Path -LiteralPath $temporaryArtifactPath) {
    Stop-WithMessage "BLOCK: A previous temporary release download exists. Inspect and remove it manually before retrying: $temporaryArtifactPath"
}

Invoke-WebRequest -UseBasicParsing -Uri $releaseUrl -OutFile $temporaryArtifactPath
$downloadedSha256 = (Get-FileHash -LiteralPath $temporaryArtifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($downloadedSha256 -ne $expectedSha256) {
    Stop-WithMessage "BLOCK: Downloaded LibreClinica 1.4.0 WAR failed SHA-256 verification. Expected $expectedSha256 but calculated $downloadedSha256. The temporary artifact was preserved for investigation: $temporaryArtifactPath"
}

Move-Item -LiteralPath $temporaryArtifactPath -Destination $artifactPath
Write-Output "PASS: Downloaded and SHA-256 verified official LibreClinica 1.4.0 WAR: $artifactPath"
