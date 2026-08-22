[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$stagingRoot = Join-Path $projectRoot '.runtime\macos-lite-source-staging'
$bundleRoot = Join-Path $stagingRoot 'ClinicalReportExtractorLite-macos-build-source'
$archivePath = Join-Path $projectRoot 'dist\ClinicalReportExtractorLite-macos-build-source.zip'

function Assert-ProjectDescendant {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith("$projectRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the project root: $resolved"
    }
    return $resolved
}

function Remove-VerifiedTarget {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = Assert-ProjectDescendant -Path $Path
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

Remove-VerifiedTarget -Path $stagingRoot
Remove-VerifiedTarget -Path $archivePath
New-Item -ItemType Directory -Path $bundleRoot -Force | Out-Null

foreach ($directory in @('app', 'packaging', 'scripts', 'tests', 'docs', '.github')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $directory) -Destination $bundleRoot -Recurse
}
foreach ($file in @('README.md', 'PRD.md', 'Tech-Spec.md', 'pyproject.toml')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $bundleRoot
}
New-Item -ItemType Directory -Path (Join-Path $bundleRoot 'vendor') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'vendor\tessdata_fast') -Destination (Join-Path $bundleRoot 'vendor') -Recurse

Get-ChildItem -LiteralPath $bundleRoot -Recurse -Force -Directory -Filter '__pycache__' |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $bundleRoot -Recurse -Force -File -Filter '*.pyc' |
    Remove-Item -Force

$configTarget = Join-Path $bundleRoot 'config'
New-Item -ItemType Directory -Path $configTarget -Force | Out-Null
foreach ($configName in @(
    'chinese_lab_aliases.v0.1.json',
    'clinical_quality_rules.v1.json',
    'pulmonary-function-field-dictionary.v1.json',
    'rct-full-field-dictionary.v0.2.json',
    'synthetic_lab_mapping.v0.1.json'
)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "config\$configName") -Destination $configTarget
}

$forbidden = Get-ChildItem -LiteralPath $bundleRoot -Recurse -Force -File | Where-Object {
    $relativePath = $_.FullName.Substring($bundleRoot.Length).TrimStart('\')
    $_.Name -eq '.env' -or
    $_.Extension -in @('.db', '.sqlite', '.sqlite3', '.log', '.key', '.pem', '.p12', '.mobileprovision') -or
    $relativePath -match '(?i)(^|[\\/])(\.runtime|dist|build|__pycache__|\.venv)([\\/]|$)'
}
if ($forbidden) {
    throw "Forbidden runtime, credential or build artifacts entered the macOS source bundle."
}

New-Item -ItemType Directory -Path (Split-Path -Parent $archivePath) -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($archivePath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    Get-ChildItem -LiteralPath $bundleRoot -Recurse -Force -File | Sort-Object FullName | ForEach-Object {
        $relative = $_.FullName.Substring($bundleRoot.Length).TrimStart('\').Replace('\', '/')
        $entryName = "ClinicalReportExtractorLite-macos-build-source/$relative"
        $entry = $archive.CreateEntry($entryName, [IO.Compression.CompressionLevel]::Optimal)
        $inputStream = [IO.File]::OpenRead($_.FullName)
        $outputStream = $entry.Open()
        try {
            $inputStream.CopyTo($outputStream)
        } finally {
            $outputStream.Dispose()
            $inputStream.Dispose()
        }
    }
} finally {
    $archive.Dispose()
}
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw 'macOS source ZIP creation failed.'
}
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
Remove-VerifiedTarget -Path $stagingRoot

Write-Output "PASS: macOS build-source ZIP: $archivePath"
Write-Output "SHA256: $archiveHash"
