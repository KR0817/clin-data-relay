[CmdletBinding()]
param(
    [int]$VerificationPort = 8012,
    [int]$LibreClinicaVerificationPort = 18082,
    [int]$MailVerificationPort = 11082,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$spec = Join-Path $projectRoot 'packaging\ClinicalEdcCompanion.spec'
$distRoot = Join-Path $projectRoot 'dist\windows-x64'
$bundleDirectory = Join-Path $distRoot 'ClinicalEdcCompanion'
$archivePath = Join-Path $projectRoot 'dist\ClinicalEdcCompanion-windows-x64.zip'
$verificationPath = Join-Path $projectRoot 'dist\ClinicalEdcCompanion-windows-x64.verification.json'
$buildRoot = Join-Path $projectRoot 'build\pyinstaller-windows'
$qaRoot = Join-Path $projectRoot '.runtime\portable-build-qa'
$tesseractRoot = 'C:\Program Files\Tesseract-OCR'
$portableSourceRoot = Join-Path $projectRoot 'infrastructure\libreclinica\portable'
$portableSeedPath = Join-Path $portableSourceRoot 'seed\libreclinica-portable-synthetic.dump'
$portableImage = 'clinical-edc-companion/libreclinica:1.4.0-sandbox'
$portableComposeProject = 'clinical-edc-portable-build-qa'
$libreClinicaWebWarSha256 = '25378635ab396195d2bc8d58ee2988383fccf0699d2c5222800c8a37524179c7'
$libreClinicaWsWarSha256 = '1f57e077d30f39b2f6c7b584ddd405420b3a990d33773fdb122019c0a8083487'

function Assert-ProjectDescendant {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    $prefix = "$projectRoot\"
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
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

function Test-PortableLibreClinicaImage {
    & docker image inspect $portableImage *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    $hashOutput = @(& docker run --rm --entrypoint sha256sum $portableImage `
        '/usr/local/tomcat/webapps/LibreClinica.war' `
        '/usr/local/tomcat/webapps/LibreClinica-ws.war')
    if ($LASTEXITCODE -ne 0) { return $false }
    $joined = $hashOutput -join "`n"
    return $joined.Contains($libreClinicaWebWarSha256) -and $joined.Contains($libreClinicaWsWarSha256)
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python is missing: $python"
}
if (-not (Test-Path -LiteralPath $spec -PathType Leaf)) {
    throw "PyInstaller spec is missing: $spec"
}
if (-not (Test-Path -LiteralPath (Join-Path $tesseractRoot 'tesseract.exe') -PathType Leaf)) {
    throw "Tesseract runtime is missing: $tesseractRoot"
}
if ($VerificationPort -lt 1024 -or $VerificationPort -gt 65535) {
    throw 'VerificationPort must be between 1024 and 65535.'
}
foreach ($port in @($LibreClinicaVerificationPort, $MailVerificationPort)) {
    if ($port -lt 1024 -or $port -gt 65535) {
        throw 'LibreClinica and mail verification ports must be between 1024 and 65535.'
    }
}
if (-not (Test-Path -LiteralPath $portableSeedPath -PathType Leaf)) {
    throw "The clean LibreClinica seed is missing: $portableSeedPath"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker Desktop is required to build the integrated portable archive.'
}
& docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop must be running to build the integrated portable archive.'
}

if (-not $SkipTests) {
    & $python -m pytest `
        'tests\test_windows_launcher.py' `
        'tests\test_runtime_scripts.py' `
        'tests\test_offline_package.py' `
        'tests\test_spreadsheet_export.py' `
        'tests\test_api.py::test_homepage_exposes_compact_ai_toggle_bulk_accept_admin_dictionary_and_one_click_export' `
        -q
    if ($LASTEXITCODE -ne 0) {
        throw 'Focused portable-distribution tests failed.'
    }
}

Remove-VerifiedTarget -Path $distRoot
Remove-VerifiedTarget -Path $buildRoot
Remove-VerifiedTarget -Path $archivePath
Remove-VerifiedTarget -Path $verificationPath
Remove-VerifiedTarget -Path $qaRoot
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

Push-Location $projectRoot
try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $distRoot `
        --workpath $buildRoot `
        $spec
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller build failed.'
    }
} finally {
    Pop-Location
}

$executablePath = Join-Path $bundleDirectory 'ClinicalEdcCompanion.exe'
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "Built executable is missing: $executablePath"
}

$ocrTarget = Join-Path $bundleDirectory 'runtime\tesseract'
New-Item -ItemType Directory -Path $ocrTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $tesseractRoot 'tesseract.exe') -Destination $ocrTarget
Get-ChildItem -LiteralPath $tesseractRoot -Filter '*.dll' -File | Copy-Item -Destination $ocrTarget

if (-not (Test-PortableLibreClinicaImage)) {
    & docker build `
        --pull=false `
        -f (Join-Path $projectRoot 'infrastructure\libreclinica\Dockerfile.release.sandbox') `
        -t $portableImage `
        $projectRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'The pinned portable LibreClinica image build failed.'
    }
}
if (-not (Test-PortableLibreClinicaImage)) {
    throw 'The portable LibreClinica image does not contain both checksum-verified WAR files.'
}

Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\README-START.txt') -Destination $bundleDirectory
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\THIRD-PARTY-NOTICES.txt') -Destination $bundleDirectory
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination (Join-Path $bundleDirectory 'LICENSE')
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\SOURCE-CODE.txt') -Destination $bundleDirectory
foreach ($entryPoint in @(
    'Start-Clinical-EDC.cmd',
    'Stop-LibreClinica.cmd',
    'Show-LibreClinica-Login.cmd',
    'Install-Docker-Desktop.cmd',
    'Diagnose-This-PC.cmd',
    'Repair-Docker-Prerequisites.cmd'
)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\$entryPoint") -Destination $bundleDirectory
}
$recipientScripts = Join-Path $bundleDirectory 'scripts'
$recipientDocs = Join-Path $bundleDirectory 'docs'
$licenseDirectory = Join-Path $bundleDirectory 'third-party-licenses'
New-Item -ItemType Directory -Path $recipientScripts, $recipientDocs, $licenseDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\configure_kimi.ps1') -Destination (Join-Path $recipientScripts 'configure_kimi.ps1')
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\configure_libreclinica_portable.ps1') -Destination (Join-Path $recipientScripts 'configure_libreclinica.ps1')
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\start_portable_stack.ps1') -Destination $recipientScripts
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\stop_portable_stack.ps1') -Destination $recipientScripts
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\show_libreclinica_login.ps1') -Destination $recipientScripts
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\portable_host_preflight.ps1') -Destination $recipientScripts
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\diagnose_portable_host.ps1') -Destination $recipientScripts
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\repair_docker_prerequisites.ps1') -Destination $recipientScripts
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\windows-portable-distribution.md') -Destination $recipientDocs
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\portable-runtime-contract.md') -Destination $recipientDocs

$portableTargetRoot = Join-Path $bundleDirectory 'libreclinica'
$portableImageDirectory = Join-Path $portableTargetRoot 'images'
$portableInitDirectory = Join-Path $portableTargetRoot 'init'
$portableSeedDirectory = Join-Path $portableTargetRoot 'seed'
New-Item -ItemType Directory -Path $portableImageDirectory, $portableInitDirectory, $portableSeedDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $portableSourceRoot 'compose.portable.yaml') -Destination $portableTargetRoot
Copy-Item -LiteralPath (Join-Path $portableSourceRoot 'init\10-restore.sh') -Destination $portableInitDirectory
Copy-Item -LiteralPath $portableSeedPath -Destination $portableSeedDirectory
$portableImageArchive = Join-Path $portableImageDirectory 'libreclinica-stack.tar'
& docker save --output $portableImageArchive $portableImage 'postgres:16-alpine' 'marlonb/mailcrab:v1.1.0'
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $portableImageArchive -PathType Leaf)) {
    throw 'The offline LibreClinica Docker image archive could not be created.'
}
$offlineManifestPath = Join-Path $portableTargetRoot 'OFFLINE-ASSETS.sha256'
$offlineManifestLines = Get-ChildItem -LiteralPath $portableTargetRoot -Recurse -File |
    Where-Object { $_.FullName -ne $offlineManifestPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relativePath = $_.FullName.Substring($portableTargetRoot.Length).TrimStart('\').Replace('\', '/')
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$hash  $relativePath"
    }
[IO.File]::WriteAllLines($offlineManifestPath, $offlineManifestLines, (New-Object Text.UTF8Encoding($false)))

$sitePackages = (& $python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
$openpyxlLicense = Join-Path $sitePackages 'openpyxl-3.1.5.dist-info\LICENCE.rst'
$pyinstallerLicense = Join-Path $sitePackages 'pyinstaller-6.21.0.dist-info\licenses\COPYING.txt'
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
Copy-Item -LiteralPath (Join-Path $projectRoot 'vendor\LibreClinica\LICENSE') -Destination (Join-Path $licenseDirectory 'LibreClinica-LICENSE.txt')

$forbiddenFiles = Get-ChildItem -LiteralPath $bundleDirectory -Recurse -File | Where-Object {
    $_.Name -eq '.env' -or
    $_.Extension -in @('.db', '.sqlite', '.sqlite3', '.log', '.key', '.pem') -or
    $_.Name -match '(?i)(credential|api[-_]?key).+\.json$'
}
if ($forbiddenFiles) {
    $relativeForbidden = $forbiddenFiles | ForEach-Object { $_.FullName.Substring($bundleDirectory.Length).TrimStart('\') }
    throw "Forbidden secret/data artifacts entered the bundle: $($relativeForbidden -join ', ')"
}
foreach ($forbiddenDirectory in @('.runtime', 'data', 'uploads', 'backups')) {
    if (Test-Path -LiteralPath (Join-Path $bundleDirectory $forbiddenDirectory)) {
        throw "Forbidden runtime directory entered the bundle: $forbiddenDirectory"
    }
}

New-Item -ItemType Directory -Path $qaRoot -Force | Out-Null
$stdoutPath = Join-Path $qaRoot 'stdout.log'
$stderrPath = Join-Path $qaRoot 'stderr.log'
$previousDataRoot = [Environment]::GetEnvironmentVariable('COMPANION_PORTABLE_DATA_ROOT', 'Process')
$env:COMPANION_PORTABLE_DATA_ROOT = $qaRoot
$process = $null
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
    $health = $null
    do {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) {
            break
        }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$VerificationPort/api/health" -TimeoutSec 2
        } catch {
            $health = $null
        }
    } while ($null -eq $health -and (Get-Date) -lt $deadline)

    if ($null -eq $health) {
        $stderrTail = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -LiteralPath $stderrPath -Tail 60) -join "`n" } else { '' }
        throw "Built EXE did not become healthy within 60 seconds.`n$stderrTail"
    }
    if (
        $health.status -ne 'ok' -or
        $health.data_boundary -ne 'synthetic_only' -or
        $health.local_ocr -ne 'local_only' -or
        $health.excel_export -ne 'ready' -or
        $health.kimi_integration -ne 'key_required' -or
        $health.edc_adapter -ne 'fail_closed_simulation_only' -or
        $health.production_readiness.status -ne 'BLOCK'
    ) {
        throw 'Built EXE health state did not match the fail-closed portable contract.'
    }
    & $python `
        (Join-Path $projectRoot 'scripts\verify_portable_http.py') `
        --base-url "http://127.0.0.1:$VerificationPort" `
        --work-directory (Join-Path $qaRoot 'http-e2e')
    if ($LASTEXITCODE -ne 0) {
        throw 'Built EXE OCR/Excel HTTP verification failed.'
    }
    $verification = [ordered]@{
        verified_at = (Get-Date).ToUniversalTime().ToString('o')
        executable_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $executablePath).Hash.ToLowerInvariant()
        portable_http_ocr_candidates = 4
        portable_http_excel_export = 'ready'
        health = [ordered]@{
            status = $health.status
            environment = $health.environment
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

$portableBundleCompose = Join-Path $bundleDirectory 'libreclinica\compose.portable.yaml'
$qaRuntimeDirectory = Join-Path $qaRoot '.runtime'
$qaKimiCredential = Join-Path $qaRuntimeDirectory 'kimi-api-key.txt'
$integratedStdoutPath = Join-Path $qaRoot 'integrated-stdout.log'
$integratedStderrPath = Join-Path $qaRoot 'integrated-stderr.log'
$previousLibreClinicaBaseUrl = [Environment]::GetEnvironmentVariable('COMPANION_PORTABLE_LIBRECLINICA_BASE_URL', 'Process')
$env:COMPANION_PORTABLE_DATA_ROOT = $qaRoot
$env:COMPANION_PORTABLE_LIBRECLINICA_BASE_URL = "http://127.0.0.1:$LibreClinicaVerificationPort"
$env:LIBRECLINICA_HOST_PORT = "$LibreClinicaVerificationPort"
$env:LIBRECLINICA_SMTP_HOST_PORT = "$MailVerificationPort"
$integratedProcess = $null
try {
    & docker compose -p $portableComposeProject -f $portableBundleCompose down --volumes --remove-orphans | Out-Null
    New-Item -ItemType Directory -Path $qaRuntimeDirectory -Force | Out-Null
    [IO.File]::WriteAllText($qaKimiCredential, 'synthetic-build-verification-key', (New-Object Text.UTF8Encoding($false)))
    & docker compose -p $portableComposeProject -f $portableBundleCompose up -d
    if ($LASTEXITCODE -ne 0) { throw 'The clean portable LibreClinica QA stack could not start.' }

    $qaDatabaseContainer = (& docker compose -p $portableComposeProject -f $portableBundleCompose ps -q db).Trim()
    if ($qaDatabaseContainer -notmatch '^[0-9a-f]{12,64}$') {
        throw 'The clean portable LibreClinica QA database container is missing.'
    }
    & (Join-Path $bundleDirectory 'scripts\configure_libreclinica.ps1') `
        -DatabaseContainer $qaDatabaseContainer `
        -RuntimeDirectory $qaRuntimeDirectory `
        -GenerateLocalPassword `
        -SuppressPasswordDisplay
    if ($LASTEXITCODE -ne 0) { throw 'The clean portable LibreClinica QA accounts could not be configured.' }

    $libreClinicaDeadline = (Get-Date).AddMinutes(5)
    $libreClinicaReady = $false
    do {
        try {
            $loginResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$LibreClinicaVerificationPort/LibreClinica/pages/login/login" -UseBasicParsing -TimeoutSec 5
            $wsdlResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$LibreClinicaVerificationPort/LibreClinica-ws/ws/studySubject/v1/studySubjectWsdl.wsdl" -UseBasicParsing -TimeoutSec 5
            $libreClinicaReady = $loginResponse.StatusCode -eq 200 -and $wsdlResponse.StatusCode -eq 200
        } catch {
            $libreClinicaReady = $false
        }
        if (-not $libreClinicaReady) { Start-Sleep -Seconds 3 }
    } while (-not $libreClinicaReady -and (Get-Date) -lt $libreClinicaDeadline)
    if (-not $libreClinicaReady) { throw 'The clean portable LibreClinica QA stack did not become web/SOAP ready.' }

    $integratedProcess = Start-Process `
        -FilePath $executablePath `
        -ArgumentList '--port', "$VerificationPort", '--no-browser' `
        -WorkingDirectory $bundleDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $integratedStdoutPath `
        -RedirectStandardError $integratedStderrPath `
        -PassThru
    $integratedDeadline = (Get-Date).AddSeconds(90)
    $integratedHealth = $null
    do {
        Start-Sleep -Milliseconds 500
        if ($integratedProcess.HasExited) { break }
        try {
            $integratedHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$VerificationPort/api/health" -TimeoutSec 2
        } catch {
            $integratedHealth = $null
        }
    } while ($null -eq $integratedHealth -and (Get-Date) -lt $integratedDeadline)
    if ($null -eq $integratedHealth) {
        throw 'The integrated portable EXE did not become healthy.'
    }
    if (
        $integratedHealth.status -ne 'ok' -or
        $integratedHealth.kimi_integration -ne 'ready' -or
        $integratedHealth.edc_adapter -ne 'libreclinica_soap' -or
        $integratedHealth.production_readiness.status -ne 'BLOCK'
    ) {
        throw 'The integrated portable EXE health state did not match the Kimi/LibreClinica contract.'
    }

    & $python `
        (Join-Path $projectRoot 'scripts\verify_portable_libreclinica_http.py') `
        --base-url "http://127.0.0.1:$VerificationPort" `
        --db-container $qaDatabaseContainer `
        --work-directory (Join-Path $qaRoot 'libreclinica-http-e2e')
    if ($LASTEXITCODE -ne 0) {
        throw 'The clean portable OCR/review/LibreClinica SOAP verification failed.'
    }
    $verification.integrated_portable = [ordered]@{
        offline_images = @($portableImage, 'postgres:16-alpine', 'marlonb/mailcrab:v1.1.0')
        clean_seed_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $portableSeedPath).Hash.ToLowerInvariant()
        initial_subject_count = 0
        kimi_integration = $integratedHealth.kimi_integration
        edc_adapter = $integratedHealth.edc_adapter
        ocr_review_soap_submission = 'verified'
        authority_readback_value = '4.50'
    }
    $verification | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $verificationPath -Encoding UTF8
} finally {
    if ($null -ne $integratedProcess -and -not $integratedProcess.HasExited) {
        Stop-Process -Id $integratedProcess.Id -Force
        $integratedProcess.WaitForExit(10000)
    }
    & docker compose -p $portableComposeProject -f $portableBundleCompose down --volumes --remove-orphans | Out-Null
    if ($null -eq $previousLibreClinicaBaseUrl) {
        Remove-Item Env:COMPANION_PORTABLE_LIBRECLINICA_BASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:COMPANION_PORTABLE_LIBRECLINICA_BASE_URL = $previousLibreClinicaBaseUrl
    }
}

$manifestPath = Join-Path $bundleDirectory 'MANIFEST.sha256'
$manifestLines = Get-ChildItem -LiteralPath $bundleDirectory -Recurse -File |
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
    throw 'Portable ZIP creation failed.'
}

$archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
Write-Output "PASS: Portable folder: $bundleDirectory"
Write-Output "PASS: Portable ZIP: $archivePath"
Write-Output "PASS: Verification report: $verificationPath"
Write-Output "SHA256: $archiveHash"
