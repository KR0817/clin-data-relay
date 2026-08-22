[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$bundleRoot = Split-Path -Parent $PSScriptRoot
$encryptedLoginPath = Join-Path $bundleRoot '.runtime\libreclinica-login.dpapi.json'
if (-not (Test-Path -LiteralPath $encryptedLoginPath -PathType Leaf)) {
    throw 'No local LibreClinica login exists yet. Run Start-Clinical-EDC.cmd first.'
}

$payload = Get-Content -LiteralPath $encryptedLoginPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($payload.username) -or [string]::IsNullOrWhiteSpace($payload.encrypted_password)) {
    throw 'The local LibreClinica login file is invalid.'
}
$securePassword = ConvertTo-SecureString -String $payload.encrypted_password
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    Write-Output "LibreClinica username: $($payload.username)"
    Write-Output "LibreClinica password: $plainPassword"
} finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    $plainPassword = $null
    $securePassword = $null
}
