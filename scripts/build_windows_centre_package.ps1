[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CentreCode,
    [Parameter(Mandatory = $true)][string]$Username,
    [int]$VerificationPort = 8021,
    [switch]$SkipBaseBuild
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$baseBundle = Join-Path $projectRoot 'dist\windows-lite-x64\ClinicalReportExtractorLite'
$centreRoot = Join-Path $projectRoot "dist\centres\$CentreCode"
$bundleDirectory = Join-Path $centreRoot "ClinicalReportExtractorLite-$CentreCode"
$archivePath = Join-Path $projectRoot "dist\ClinicalReportExtractorLite-$CentreCode-windows-x64.zip"
$verificationPath = Join-Path $projectRoot "dist\ClinicalReportExtractorLite-$CentreCode-windows-x64.verification.json"
$qaRoot = Join-Path $projectRoot ".runtime\centre-package-qa\$CentreCode"

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
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Test-Path -LiteralPath $resolved)) { return }
        try {
            Remove-Item -LiteralPath $resolved -Recurse -Force
            return
        } catch [IO.IOException] {
            if ($attempt -eq 19) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

if ($CentreCode -cnotmatch '^[A-Z][A-Z0-9_-]{1,31}$') {
    throw 'CentreCode must contain 2-32 uppercase letters, digits, underscores or hyphens.'
}
if ($Username.Length -gt 254 -or $Username -notmatch "^[A-Za-z0-9.!#$%&'*+/=?^_``{|}~-]+@[A-Za-z0-9.-]+$") {
    throw 'Username must be a bounded email-like account name.'
}
if ($VerificationPort -lt 1024 -or $VerificationPort -gt 65535) {
    throw 'VerificationPort must be between 1024 and 65535.'
}
if (-not $SkipBaseBuild) {
    & (Join-Path $projectRoot 'scripts\build_windows_lite.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Base Lite build failed.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $baseBundle 'Start-Clinical-EDC-Lite.exe') -PathType Leaf)) {
    throw 'Verified base Lite bundle is missing.'
}

Remove-VerifiedTarget -Path $centreRoot
Remove-VerifiedTarget -Path $archivePath
Remove-VerifiedTarget -Path $verificationPath
Remove-VerifiedTarget -Path $qaRoot
New-Item -ItemType Directory -Path $centreRoot -Force | Out-Null
Copy-Item -LiteralPath $baseBundle -Destination $bundleDirectory -Recurse

$profile = [ordered]@{
    profile_type = 'clinical-edc-centre-lite'
    profile_version = 1
    centre_code = $CentreCode
    username = $Username
}
[IO.File]::WriteAllText(
    (Join-Path $bundleDirectory 'centre-profile.json'),
    (($profile | ConvertTo-Json -Depth 3) + "`n"),
    (New-Object Text.UTF8Encoding($false))
)
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\README-START-CENTRE.txt') `
    -Destination (Join-Path $bundleDirectory 'README-START.txt') -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\Reset-Centre-Password.cmd') `
    -Destination (Join-Path $bundleDirectory 'Reset-Centre-Password.cmd') -Force

$forbiddenFiles = Get-ChildItem -LiteralPath $bundleDirectory -Recurse -Force -File | Where-Object {
    $_.Name -eq '.env' -or
    $_.Extension -in @('.db', '.sqlite', '.sqlite3', '.log', '.key', '.pem') -or
    $_.Name -match '(?i)(credential|api[-_]?key).+\.json$'
}
if ($forbiddenFiles) {
    throw "Forbidden data or secret artifact entered centre bundle: $($forbiddenFiles.Name -join ', ')"
}
foreach ($forbiddenDirectory in @('.runtime', 'data', 'uploads', 'backups')) {
    if (Test-Path -LiteralPath (Join-Path $bundleDirectory $forbiddenDirectory)) {
        throw "Forbidden runtime directory entered centre bundle: $forbiddenDirectory"
    }
}

$manifestPath = Join-Path $bundleDirectory 'MANIFEST.sha256'
$manifestLines = Get-ChildItem -LiteralPath $bundleDirectory -Recurse -Force -File |
    Where-Object { $_.FullName -ne $manifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relativePath = $_.FullName.Substring($bundleDirectory.Length).TrimStart('\').Replace('\', '/')
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$hash  $relativePath"
    }
[IO.File]::WriteAllLines($manifestPath, $manifestLines, (New-Object Text.UTF8Encoding($false)))

New-Item -ItemType Directory -Path $qaRoot -Force | Out-Null
$syntheticPdfPath = Join-Path $qaRoot 'synthetic-pulmonary-report.pdf'
& $python (Join-Path $projectRoot 'scripts\generate_synthetic_pulmonary_pdf.py') $syntheticPdfPath
if ($LASTEXITCODE -ne 0) { throw 'Synthetic PDF generation failed.' }
$syntheticImagePath = Join-Path $qaRoot 'synthetic-check-sheet.png'
& $python (Join-Path $projectRoot 'scripts\generate_synthetic_check_sheet.py') $syntheticImagePath
if ($LASTEXITCODE -ne 0) { throw 'Synthetic image generation failed.' }
Compress-Archive -LiteralPath $bundleDirectory -DestinationPath $archivePath -CompressionLevel Optimal
$extractedRoot = Join-Path $qaRoot 'extracted'
Expand-Archive -LiteralPath $archivePath -DestinationPath $extractedRoot
$blackboxBundle = Join-Path $extractedRoot "ClinicalReportExtractorLite-$CentreCode"
$qaDataRoot = Join-Path $qaRoot 'runtime'
if (-not (Test-Path -LiteralPath (Join-Path $blackboxBundle 'Start-Clinical-EDC-Lite.exe') -PathType Leaf)) {
    throw 'Extracted centre ZIP is missing its executable.'
}

$previousDataRoot = [Environment]::GetEnvironmentVariable('COMPANION_PORTABLE_DATA_ROOT', 'Process')
$env:COMPANION_PORTABLE_DATA_ROOT = $qaDataRoot
$process = $null
$health = $null
try {
    $process = Start-Process `
        -FilePath (Join-Path $blackboxBundle 'Start-Clinical-EDC-Lite.exe') `
        -ArgumentList '--port', "$VerificationPort", '--no-browser' `
        -WorkingDirectory $blackboxBundle `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $qaRoot 'stdout.log') `
        -RedirectStandardError (Join-Path $qaRoot 'stderr.log') `
        -PassThru
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) { break }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$VerificationPort/api/health" -TimeoutSec 2
        } catch {
            $health = $null
        }
    } while ($null -eq $health -and (Get-Date) -lt $deadline)
    if ($null -eq $health) { throw 'Centre Lite EXE did not become healthy within 60 seconds.' }
    if (
        $health.product_mode -ne 'lite' -or
        -not $health.setup_required -or
        $health.centre_profile.centre_code -ne $CentreCode -or
        $health.centre_profile.username -ne $Username
    ) {
        throw 'Centre Lite health scope did not match the packaged profile.'
    }
    & $python `
        (Join-Path $projectRoot 'scripts\verify_portable_lite_pdf.py') `
        --base-url "http://127.0.0.1:$VerificationPort" `
        --pdf $syntheticPdfPath `
        --image $syntheticImagePath `
        --centre-code $CentreCode `
        --username $Username `
        --database (Join-Path $qaDataRoot 'data\companion.db')
    if ($LASTEXITCODE -ne 0) { throw 'Centre package black-box verification failed.' }
} finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit(10000)
    }
    if ($null -eq $previousDataRoot) {
        Remove-Item Env:COMPANION_PORTABLE_DATA_ROOT -ErrorAction SilentlyContinue
    } else {
        $env:COMPANION_PORTABLE_DATA_ROOT = $previousDataRoot
    }
}

$previousDataRoot = [Environment]::GetEnvironmentVariable('COMPANION_PORTABLE_DATA_ROOT', 'Process')
$env:COMPANION_PORTABLE_DATA_ROOT = $qaDataRoot
try {
    $resetOutput = & (Join-Path $blackboxBundle 'Start-Clinical-EDC-Lite.exe') `
        '--reset-centre-password' 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Packaged centre password reset command failed.' }
    $resetText = $resetOutput -join "`n"
    if ($resetText -notmatch [regex]::Escape($CentreCode) -or $resetText -notmatch [regex]::Escape($Username)) {
        throw 'Packaged centre password reset output did not match its fixed profile.'
    }
} finally {
    $resetOutput = $null
    $resetText = $null
    if ($null -eq $previousDataRoot) {
        Remove-Item Env:COMPANION_PORTABLE_DATA_ROOT -ErrorAction SilentlyContinue
    } else {
        $env:COMPANION_PORTABLE_DATA_ROOT = $previousDataRoot
    }
}

$verification = [ordered]@{
    verified_at = (Get-Date).ToUniversalTime().ToString('o')
    centre_code = $CentreCode
    username = $Username
    archive_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    profile_count = 1
    account_scope = 'one_site_investigator_only'
    plaintext_password_in_archive = $false
    sender_database_in_archive = $false
    first_run_setup = 'verified'
    one_time_password_receipt = 'verified_by_ui_contract'
    local_password_reset = 'verified'
    kimi_web_configuration = 'verified'
    kimi_local_fallback = 'verified'
    pulmonary_pdf_candidates = 18
    human_review = 'verified'
    reviewed_excel_export = 'verified'
    encrypted_centre_package_export = 'verified'
    blackbox_source = 'freshly_extracted_zip'
}
$verification | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $verificationPath -Encoding UTF8
Remove-VerifiedTarget -Path $qaRoot

Write-Output "PASS: Centre bundle: $bundleDirectory"
Write-Output "PASS: Centre ZIP: $archivePath"
Write-Output "PASS: Verification: $verificationPath"
Write-Output "SHA256: $($verification.archive_sha256)"
