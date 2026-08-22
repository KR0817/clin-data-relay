[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$bundleRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$portableDataRoot = if ([string]::IsNullOrWhiteSpace($env:COMPANION_PORTABLE_DATA_ROOT)) {
    $bundleRoot
} else {
    [IO.Path]::GetFullPath($env:COMPANION_PORTABLE_DATA_ROOT)
}
$reportPath = Join-Path $portableDataRoot '.runtime\portable-host-diagnostic.json'
. (Join-Path $PSScriptRoot 'portable_host_preflight.ps1')

$state = Get-PortableHostState
$diagnostic = Resolve-PortableHostDiagnostic -State $state
Write-PortableHostDiagnostic -State $state -Diagnostic $diagnostic -Path $reportPath
Show-PortableHostDiagnostic -Diagnostic $diagnostic
Write-Output "诊断报告：$reportPath"
if (-not $diagnostic.ready) { exit 2 }
