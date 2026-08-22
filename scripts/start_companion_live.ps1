[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeDirectory = Join-Path $projectRoot '.runtime'
$kimiCredentialPath = Join-Path $runtimeDirectory 'kimi-api-key.txt'
$spreadsheetNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$spreadsheetModules = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$projectNodeModules = Join-Path $projectRoot 'node_modules'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python is missing: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $runtimeDirectory 'libreclinica-soap-credentials.json'))) {
    throw 'LibreClinica SOAP credential file is missing. Run the sandbox account bootstrap first.'
}

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
if ((Test-Path -LiteralPath $spreadsheetModules) -and -not (Test-Path -LiteralPath $projectNodeModules)) {
    New-Item -ItemType Junction -Path $projectNodeModules -Target $spreadsheetModules | Out-Null
}
if (Test-Path -LiteralPath $spreadsheetNode) {
    $env:SPREADSHEET_NODE_EXECUTABLE = $spreadsheetNode
} else {
    Remove-Item Env:SPREADSHEET_NODE_EXECUTABLE -ErrorAction SilentlyContinue
}
$env:COMPANION_EDC_MODE = 'libreclinica_soap'
$env:LIBRECLINICA_BASE_URL = 'http://127.0.0.1:8081'
$env:LIBRECLINICA_SOAP_CREDENTIALS_FILE = '.runtime/libreclinica-soap-credentials.json'
$env:LIBRECLINICA_ODM_MAPPING_FILE = 'config/libreclinica-sandbox-odm-map.json'
$env:LIBRECLINICA_ALLOW_SUBJECT_PROVISIONING = 'true'
$env:COMPANION_BACKUP_DIRECTORY = Join-Path $runtimeDirectory 'backups'
$databasePath = if ($env:COMPANION_DATABASE_PATH) { $env:COMPANION_DATABASE_PATH } else { Join-Path $projectRoot 'data\companion.db' }
if (Test-Path -LiteralPath $databasePath -PathType Leaf) {
    & $python (Join-Path $PSScriptRoot 'backup_companion_database.py') `
        --source (Resolve-Path -LiteralPath $databasePath).Path `
        --output-dir $env:COMPANION_BACKUP_DIRECTORY | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Automatic database backup and restore check failed.' }
}
Remove-Item Env:KIMI_API_KEY -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $kimiCredentialPath) {
    $env:KIMI_ENABLED = 'true'
    $env:KIMI_API_KEY_FILE = $kimiCredentialPath
    $env:KIMI_BASE_URL = 'https://api.moonshot.cn/v1'
    $env:KIMI_MODEL = 'kimi-k3'
} else {
    # Kimi is the default workflow.  Without a key the client remains
    # fail-closed and the first-run configuration prompt can be used later.
    $env:KIMI_ENABLED = 'true'
    Remove-Item Env:KIMI_API_KEY_FILE -ErrorAction SilentlyContinue
}

$stdout = Join-Path $runtimeDirectory 'companion-live.stdout.log'
$stderr = Join-Path $runtimeDirectory 'companion-live.stderr.log'

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in ($listeners | Sort-Object OwningProcess -Unique)) {
    $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $commandLine = [string]$existingProcess.CommandLine
    if ($commandLine -notmatch 'uvicorn\s+app\.main:app') {
        throw "Port $Port is occupied by an unrelated process (PID $($listener.OwningProcess)); refusing to stop it."
    }
    Stop-Process -Id $listener.OwningProcess -Force
}

$releaseDeadline = (Get-Date).AddSeconds(10)
while ((Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $releaseDeadline) {
    Start-Sleep -Milliseconds 200
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port did not become available after stopping the previous companion process."
}

$process = Start-Process `
    -FilePath $python `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) {
        break
    }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 8
        if ($health.status -eq 'ok' -and $health.excel_export -eq 'ready') {
            Write-Output "PASS: Companion started on http://127.0.0.1:$Port/ with adapter $($health.edc_adapter) (PID $($process.Id))."
            exit 0
        }
    } catch {
        # Continue until timeout; stderr is reported below.
    }
} while ((Get-Date) -lt $deadline)

if (Test-Path -LiteralPath $stderr) {
    Get-Content -LiteralPath $stderr -Tail 80
}
throw 'Companion did not become healthy within 30 seconds.'
