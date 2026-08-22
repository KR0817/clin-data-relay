[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{2,62}$')][string]$ComposeProject = 'clinical-edc-portable'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$bundleRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$composePath = Join-Path $bundleRoot 'libreclinica\compose.portable.yaml'
$executablePath = Join-Path $bundleRoot 'ClinicalEdcCompanion.exe'
$pidPath = Join-Path $bundleRoot '.runtime\companion.pid'

if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $pidText = (Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8).Trim()
    if ($pidText -match '^\d+$') {
        $process = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.Path -eq $executablePath) {
            Stop-Process -Id $process.Id
        }
    }
    Remove-Item -LiteralPath $pidPath -Force
}

if ((Test-Path -LiteralPath $composePath -PathType Leaf) -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    & docker compose -p $ComposeProject -f $composePath stop
    if ($LASTEXITCODE -ne 0) { throw 'Docker could not stop the portable LibreClinica containers.' }
}
Write-Output 'PASS: Companion and LibreClinica containers stopped. The local database volume was preserved.'
