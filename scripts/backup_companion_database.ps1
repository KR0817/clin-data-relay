[CmdletBinding()]
param(
    [string]$Source,
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not $Source) {
    $Source = Join-Path $projectRoot 'data\companion.db'
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot '.runtime\backups'
}

$resolvedSource = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath $resolvedSource -PathType Leaf)) {
    throw "Companion database not found: $resolvedSource"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python not found: $python"
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$resolvedOutput = (Resolve-Path -LiteralPath $OutputDirectory).Path
& $python (Join-Path $PSScriptRoot 'backup_companion_database.py') `
    --source $resolvedSource `
    --output-dir $resolvedOutput
if ($LASTEXITCODE -ne 0) {
    throw "Companion database backup failed with exit code $LASTEXITCODE"
}
