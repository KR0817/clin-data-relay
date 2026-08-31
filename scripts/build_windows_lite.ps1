[CmdletBinding()]
param(
    [int]$VerificationPort = 8013,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$spec = Join-Path $projectRoot 'packaging\ClinicalEdcCompanion.spec'
$binaryName = 'ClinicalReportExtractorLite'
$executableName = 'Start-Clinical-EDC-Lite'
$distRoot = Join-Path $projectRoot 'dist\windows-lite-x64'
$bundleDirectory = Join-Path $distRoot $binaryName
$archivePath = Join-Path $projectRoot 'dist\ClinicalReportExtractorLite-windows-x64.zip'
$checksumPath = Join-Path $projectRoot 'dist\ClinicalReportExtractorLite-windows-x64.sha256'
$verificationPath = Join-Path $projectRoot 'dist\ClinicalReportExtractorLite-windows-x64.verification.json'
$buildRoot = Join-Path $projectRoot 'build\pyinstaller-windows-lite'
$qaRoot = Join-Path $projectRoot '.runtime\portable-lite-build-qa'
$tesseractRoot = 'C:\Program Files\Tesseract-OCR'
$iconSource = Join-Path $projectRoot 'packaging\assets\clinical-report-extractor-lite-icon.ico'

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

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python is missing: $python"
}
if (-not (Test-Path -LiteralPath $spec -PathType Leaf)) {
    throw "PyInstaller spec is missing: $spec"
}
if (-not (Test-Path -LiteralPath $iconSource -PathType Leaf)) {
    throw "Lite application icon is missing: $iconSource"
}
if (-not (Test-Path -LiteralPath (Join-Path $tesseractRoot 'tesseract.exe') -PathType Leaf)) {
    throw "Tesseract runtime is missing: $tesseractRoot"
}
if ($VerificationPort -lt 1024 -or $VerificationPort -gt 65535) {
    throw 'VerificationPort must be between 1024 and 65535.'
}

& $python (Join-Path $projectRoot 'scripts\prepare_tessdata.py')
if ($LASTEXITCODE -ne 0) {
    throw 'Pinned Tesseract language data preparation failed.'
}

if (-not $SkipTests) {
    & $python -m pytest `
        'tests\test_windows_launcher.py' `
        'tests\test_runtime_scripts.py::test_lite_portable_entrypoint_has_no_container_runtime_dependency' `
        'tests\test_api.py::test_lite_health_reports_local_only_product_mode' `
        'tests\test_api.py::test_homepage_contains_lite_profile_for_local_recognition_review_and_export' `
        'tests\test_api.py::test_homepage_exposes_compact_ai_toggle_bulk_accept_admin_dictionary_and_one_click_export' `
        'tests\test_api.py::test_recognition_job_keeps_local_candidates_and_ids_when_kimi_fails' `
        'tests\test_pulmonary_function.py' `
        'tests\test_offline_package.py' `
        'tests\test_spreadsheet_export.py' `
        -q
    if ($LASTEXITCODE -ne 0) {
        throw 'Focused Lite distribution tests failed.'
    }
}

Remove-VerifiedTarget -Path $distRoot
Remove-VerifiedTarget -Path $buildRoot
Remove-VerifiedTarget -Path $archivePath
Remove-VerifiedTarget -Path $checksumPath
Remove-VerifiedTarget -Path $verificationPath
Remove-VerifiedTarget -Path $qaRoot
New-Item -ItemType Directory -Path $distRoot, $buildRoot -Force | Out-Null

$previousBinaryName = [Environment]::GetEnvironmentVariable('COMPANION_BINARY_NAME', 'Process')
$env:COMPANION_BINARY_NAME = $binaryName
Push-Location $projectRoot
try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $distRoot `
        --workpath $buildRoot `
        $spec
    if ($LASTEXITCODE -ne 0) {
        throw 'Lite PyInstaller build failed.'
    }
} finally {
    Pop-Location
    if ($null -eq $previousBinaryName) {
        Remove-Item Env:COMPANION_BINARY_NAME -ErrorAction SilentlyContinue
    } else {
        $env:COMPANION_BINARY_NAME = $previousBinaryName
    }
}

$executablePath = Join-Path $bundleDirectory "$executableName.exe"
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "Built Lite executable is missing: $executablePath"
}

$ocrTarget = Join-Path $bundleDirectory 'runtime\tesseract'
New-Item -ItemType Directory -Path $ocrTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $tesseractRoot 'tesseract.exe') -Destination $ocrTarget
Get-ChildItem -LiteralPath $tesseractRoot -Filter '*.dll' -File | Copy-Item -Destination $ocrTarget

$compatibilityDirectory = Join-Path $bundleDirectory 'compatibility'
$startCommandPath = Join-Path $compatibilityDirectory 'Start-Clinical-EDC-Lite.cmd'
$iconTarget = Join-Path $bundleDirectory 'ClinicalReportExtractorLite.ico'
New-Item -ItemType Directory -Path $compatibilityDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\Start-Clinical-EDC-Lite.cmd') -Destination $startCommandPath
Copy-Item -LiteralPath $iconSource -Destination $iconTarget
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\Configure-Kimi.cmd') -Destination $bundleDirectory
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\README-START-LITE.txt') -Destination (Join-Path $bundleDirectory 'README-START.txt')
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\THIRD-PARTY-NOTICES-LITE.txt') -Destination (Join-Path $bundleDirectory 'THIRD-PARTY-NOTICES.txt')
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination (Join-Path $bundleDirectory 'LICENSE')
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\SOURCE-CODE.txt') -Destination $bundleDirectory

$recipientScripts = Join-Path $bundleDirectory 'scripts'
$recipientDocs = Join-Path $bundleDirectory 'docs'
$licenseDirectory = Join-Path $bundleDirectory 'third-party-licenses'
New-Item -ItemType Directory -Path $recipientScripts, $recipientDocs, $licenseDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\configure_kimi.ps1') -Destination $recipientScripts
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\windows-lite-distribution.md') -Destination $recipientDocs

$sitePackages = (& $python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
$openpyxlLicense = Get-ChildItem -LiteralPath $sitePackages -Directory -Filter 'openpyxl-*.dist-info' |
    ForEach-Object { Join-Path $_.FullName 'LICENCE.rst' } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
$pyinstallerLicense = Get-ChildItem -LiteralPath $sitePackages -Directory -Filter 'pyinstaller-*.dist-info' |
    ForEach-Object { Join-Path $_.FullName 'licenses\COPYING.txt' } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
$pypdfLicense = Get-ChildItem -LiteralPath $sitePackages -Directory -Filter 'pypdf-*.dist-info' |
    ForEach-Object { Join-Path $_.FullName 'licenses\LICENSE' } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
$tesseractLicense = Join-Path $tesseractRoot 'doc\LICENSE'
foreach ($license in @($openpyxlLicense, $pyinstallerLicense, $pypdfLicense, $tesseractLicense)) {
    if (-not (Test-Path -LiteralPath $license -PathType Leaf)) {
        throw "Required third-party license text is missing: $license"
    }
}
Copy-Item -LiteralPath $openpyxlLicense -Destination (Join-Path $licenseDirectory 'openpyxl-LICENCE.rst')
Copy-Item -LiteralPath $pyinstallerLicense -Destination (Join-Path $licenseDirectory 'PyInstaller-COPYING.txt')
Copy-Item -LiteralPath $pypdfLicense -Destination (Join-Path $licenseDirectory 'pypdf-LICENSE.txt')
Copy-Item -LiteralPath $tesseractLicense -Destination (Join-Path $licenseDirectory 'Tesseract-LICENSE.txt')

$forbiddenFiles = Get-ChildItem -LiteralPath $bundleDirectory -Recurse -Force -File | Where-Object {
    $_.Name -eq '.env' -or
    $_.Extension -in @('.db', '.sqlite', '.sqlite3', '.log', '.key', '.pem') -or
    $_.Name -match '(?i)(credential|api[-_]?key).+\.json$'
}
if ($forbiddenFiles) {
    $relativeForbidden = $forbiddenFiles | ForEach-Object { $_.FullName.Substring($bundleDirectory.Length).TrimStart('\') }
    throw "Forbidden secret/data artifacts entered the Lite bundle: $($relativeForbidden -join ', ')"
}
foreach ($forbiddenDirectory in @('.runtime', 'data', 'uploads', 'backups')) {
    if (Test-Path -LiteralPath (Join-Path $bundleDirectory $forbiddenDirectory)) {
        throw "Forbidden runtime directory entered the Lite bundle: $forbiddenDirectory"
    }
}
$forbiddenAssetPattern = '(?i)(libreclinica|postgres|mailcrab|compose)'
$forbiddenAssets = Get-ChildItem -LiteralPath $bundleDirectory -Recurse -Force | Where-Object { $_.Name -match $forbiddenAssetPattern }
if ($forbiddenAssets) {
    $relativeAssets = $forbiddenAssets | ForEach-Object { $_.FullName.Substring($bundleDirectory.Length).TrimStart('\') }
    throw "Authority/container assets entered the Lite bundle: $($relativeAssets -join ', ')"
}

New-Item -ItemType Directory -Path $qaRoot -Force | Out-Null
$syntheticPdfPath = Join-Path $qaRoot 'synthetic-pulmonary-report.pdf'
& $python (Join-Path $projectRoot 'scripts\generate_synthetic_pulmonary_pdf.py') $syntheticPdfPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $syntheticPdfPath -PathType Leaf)) {
    throw 'Synthetic pulmonary PDF generation failed.'
}

$stdoutPath = Join-Path $qaRoot 'stdout.log'
$stderrPath = Join-Path $qaRoot 'stderr.log'
$previousDataRoot = [Environment]::GetEnvironmentVariable('COMPANION_PORTABLE_DATA_ROOT', 'Process')
$env:COMPANION_PORTABLE_DATA_ROOT = $qaRoot
$process = $null
$health = $null
try {
    $process = Start-Process `
        -FilePath $executablePath `
        -ArgumentList '--port', "$VerificationPort", '--no-browser' `
        -WorkingDirectory $bundleDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
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

    if ($null -eq $health) {
        $stderrTail = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -LiteralPath $stderrPath -Tail 60) -join "`n" } else { '' }
        throw "Built Lite EXE did not become healthy within 60 seconds.`n$stderrTail"
    }
    if (
        $health.status -ne 'ok' -or
        $health.product_mode -ne 'lite' -or
        $health.data_boundary -ne 'synthetic_only' -or
        $health.local_ocr -ne 'local_only' -or
        $health.excel_export -ne 'ready' -or
        $health.edc_adapter -ne 'fail_closed_simulation_only' -or
        $health.production_readiness.status -ne 'BLOCK'
    ) {
        throw 'Built Lite EXE health state did not match the local-only contract.'
    }

    & $python `
        (Join-Path $projectRoot 'scripts\verify_portable_lite_pdf.py') `
        --base-url "http://127.0.0.1:$VerificationPort" `
        --pdf $syntheticPdfPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Built Lite PDF/review/Excel verification failed.'
    }

    $verification = [ordered]@{
        verified_at = (Get-Date).ToUniversalTime().ToString('o')
        executable_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $executablePath).Hash.ToLowerInvariant()
        icon_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $iconTarget).Hash.ToLowerInvariant()
        primary_launcher = "$executableName.exe"
        container_runtime_required = $false
        authority_edc_included = $false
        pulmonary_pdf_candidates = 18
        human_review = 'verified'
        reviewed_excel_export = 'verified'
        health = [ordered]@{
            status = $health.status
            product_mode = $health.product_mode
            data_boundary = $health.data_boundary
            local_ocr = $health.local_ocr
            excel_export = $health.excel_export
            kimi_integration = $health.kimi_integration
            edc_adapter = $health.edc_adapter
            production_readiness = $health.production_readiness.status
        }
    }
    $verification | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $verificationPath -Encoding UTF8
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

New-Item -ItemType Directory -Path (Split-Path -Parent $archivePath) -Force | Out-Null
Compress-Archive -LiteralPath $bundleDirectory -DestinationPath $archivePath -CompressionLevel Optimal
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw 'Lite ZIP creation failed.'
}
$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(
    $checksumPath,
    "$archiveHash  $([IO.Path]::GetFileName($archivePath))`n",
    (New-Object Text.UTF8Encoding($false))
)
Remove-VerifiedTarget -Path $qaRoot

Write-Output "PASS: Lite folder: $bundleDirectory"
Write-Output "PASS: Lite ZIP: $archivePath"
Write-Output "PASS: Verification report: $verificationPath"
Write-Output "PASS: Checksum: $checksumPath"
Write-Output "SHA256: $archiveHash"
