[CmdletBinding()]
param(
    [string]$RuntimeDirectory = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) {
    Join-Path $projectRoot '.runtime'
} else {
    [IO.Path]::GetFullPath($RuntimeDirectory)
}
$credentialPath = Join-Path $runtimeDirectory 'kimi-api-key.txt'

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$secureKey = Read-Host -Prompt 'Enter the Kimi API key for this local server' -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$plainKey = $null
try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($plainKey) -or $plainKey.Length -lt 16) {
        throw 'The Kimi API key is empty or unexpectedly short.'
    }
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($credentialPath, $plainKey.Trim(), $utf8WithoutBom)
} finally {
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    $plainKey = $null
    $secureKey = $null
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $credentialPath '/inheritance:r' '/grant:r' "${identity}:(R,W)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'The Kimi credential was written but its Windows ACL could not be restricted.'
}

Write-Output "PASS: Kimi credential saved to the ignored runtime directory for the current Windows account."
Write-Output "Restart the companion to enable Kimi."
