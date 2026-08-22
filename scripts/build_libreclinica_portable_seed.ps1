[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{12,64}$')][string]$SourceDatabaseContainer
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$workRoot = Join-Path $projectRoot '.runtime\portable-seed-builder'
$sourceDumpPath = Join-Path $workRoot 'source.dump'
$dumpErrorPath = Join-Path $workRoot 'source-dump.stderr.log'
$outputDirectory = Join-Path $projectRoot 'infrastructure\libreclinica\portable\seed'
$outputPath = Join-Path $outputDirectory 'libreclinica-portable-synthetic.dump'
$builderContainer = 'clinical-edc-portable-seed-builder-db'
$verifyContainer = 'clinical-edc-portable-seed-builder-verify-db'
$postgresImage = 'postgres:16-alpine'
$studyIdentifier = 'SYNTHETIC-OCR-LAB-2026-08'

function Assert-ProjectDescendant {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith("$projectRoot\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the project root: $resolved"
    }
    return $resolved
}

function Remove-GeneratedFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = Assert-ProjectDescendant -Path $Path
    if (Test-Path -LiteralPath $resolved -PathType Leaf) {
        Remove-Item -LiteralPath $resolved -Force
    }
}

function Remove-BuilderContainer {
    param([Parameter(Mandatory = $true)][string]$Name)
    $existingContainer = (@(& docker container ls -aq --filter "name=^/${Name}$") -join '').Trim()
    if (-not [string]::IsNullOrWhiteSpace($existingContainer)) {
        & docker rm -f $Name | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not remove isolated builder container: $Name" }
    }
}

function Start-BuilderPostgres {
    param([Parameter(Mandatory = $true)][string]$Name)
    $containerId = (& docker run -d --name $Name -e POSTGRES_PASSWORD=clinica -e POSTGRES_USER=clinica -e POSTGRES_DB=libreclinica $postgresImage).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($containerId)) {
        throw "Could not start isolated PostgreSQL container: $Name"
    }
    $deadline = (Get-Date).AddMinutes(2)
    do {
        & docker exec $Name pg_isready -U clinica -d libreclinica *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Isolated PostgreSQL container did not become ready: $Name"
}

function Restore-Dump {
    param(
        [Parameter(Mandatory = $true)][string]$Container,
        [Parameter(Mandatory = $true)][string]$HostDumpPath
    )
    & docker cp $HostDumpPath "${Container}:/tmp/portable.dump" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not copy the dump into $Container." }
    & docker exec $Container pg_restore --exit-on-error --no-owner --no-privileges -U clinica -d libreclinica /tmp/portable.dump
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed in $Container." }
}

function Assert-CleanSeed {
    param([Parameter(Mandatory = $true)][string]$Container)
    $query = @"
SELECT
  (SELECT count(*) FROM subject),
  (SELECT count(*) FROM study_subject),
  (SELECT count(*) FROM study_event),
  (SELECT count(*) FROM event_crf),
  (SELECT count(*) FROM item_data),
  (SELECT count(*) FROM audit_user_login),
  (SELECT count(*) FROM audit_log_event),
  (SELECT count(*) FROM study WHERE unique_identifier='$studyIdentifier'),
  (SELECT count(*) FROM study_event_definition WHERE study_id=(SELECT study_id FROM study WHERE unique_identifier='$studyIdentifier')),
  (SELECT count(*) FROM user_account WHERE user_name IN ('sandbox_admin','site_a_investigator','companion_soap') AND passwd = repeat('0', 40));
"@
    $result = (& docker exec $Container psql -U clinica -d libreclinica -v ON_ERROR_STOP=1 -A -t -F ',' -c $query).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Seed verification query failed in $Container." }
    $values = $result.Split(',')
    if ($values.Count -ne 10) { throw "Unexpected seed verification result: $result" }
    if (($values[0..6] | Where-Object { $_ -ne '0' }).Count -ne 0) {
        throw "The seed still contains clinical or login-audit rows: $result"
    }
    if ($values[7] -ne '1' -or [int]$values[8] -lt 4 -or $values[9] -ne '3') {
        throw "The seed is missing its study, event or predefined-account metadata: $result"
    }
}

New-Item -ItemType Directory -Path $workRoot, $outputDirectory -Force | Out-Null
Remove-GeneratedFile -Path $sourceDumpPath
Remove-GeneratedFile -Path $dumpErrorPath
Remove-GeneratedFile -Path $outputPath
Remove-BuilderContainer -Name $builderContainer
Remove-BuilderContainer -Name $verifyContainer

try {
    $dumpProcess = Start-Process -FilePath 'docker.exe' -ArgumentList @(
        'exec', $SourceDatabaseContainer, 'pg_dump', '-Fc', '--no-owner', '--no-privileges',
        '-U', 'clinica', '-d', 'libreclinica'
    ) -RedirectStandardOutput $sourceDumpPath -RedirectStandardError $dumpErrorPath -Wait -PassThru -NoNewWindow
    if (
        $dumpProcess.ExitCode -ne 0 -or
        -not (Test-Path -LiteralPath $sourceDumpPath -PathType Leaf) -or
        (Get-Item -LiteralPath $sourceDumpPath).Length -lt 5
    ) {
        throw 'pg_dump failed for the source synthetic database.'
    }

    Start-BuilderPostgres -Name $builderContainer
    Restore-Dump -Container $builderContainer -HostDumpPath $sourceDumpPath
    $sanitizeSql = @"
BEGIN;
TRUNCATE TABLE subject CASCADE;
TRUNCATE TABLE audit_user_login, audit_log_event, audit_event_context, audit_event_values, audit_event RESTART IDENTITY CASCADE;
UPDATE user_account
SET passwd = repeat('0', 40),
    passwd_timestamp = NULL,
    passwd_challenge_question = NULL,
    passwd_challenge_answer = NULL,
    date_lastvisit = NULL,
    access_code = NULL,
    api_key = NULL,
    authsecret = NULL,
    account_non_locked = true,
    lock_counter = 0
WHERE true;
COMMIT;
"@
    $sanitizeSql | & docker exec -i $builderContainer psql -U clinica -d libreclinica -v ON_ERROR_STOP=1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The clean-seed sanitization transaction failed.' }
    Assert-CleanSeed -Container $builderContainer

    & docker exec $builderContainer pg_dump -Fc --no-owner --no-privileges -U clinica -d libreclinica --file=/tmp/libreclinica-portable-synthetic.dump
    if ($LASTEXITCODE -ne 0) { throw 'The sanitized pg_dump failed.' }
    & docker cp "${builderContainer}:/tmp/libreclinica-portable-synthetic.dump" $outputPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy the sanitized seed to the project.' }

    Start-BuilderPostgres -Name $verifyContainer
    Restore-Dump -Container $verifyContainer -HostDumpPath $outputPath
    Assert-CleanSeed -Container $verifyContainer
    Write-Output "PASS: Clean portable LibreClinica seed: $outputPath"
    Write-Output "SHA256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $outputPath).Hash.ToLowerInvariant())"
} finally {
    Remove-BuilderContainer -Name $verifyContainer
    Remove-BuilderContainer -Name $builderContainer
    Remove-GeneratedFile -Path $sourceDumpPath
    Remove-GeneratedFile -Path $dumpErrorPath
}
