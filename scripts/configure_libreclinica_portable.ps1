[CmdletBinding()]
param(
    [string]$DatabaseContainer = '',
    [string]$RuntimeDirectory = '',
    [switch]$ApplyExisting,
    [switch]$GenerateLocalPassword,
    [switch]$SuppressPasswordDisplay
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = if ([string]::IsNullOrWhiteSpace($RuntimeDirectory)) {
    Join-Path $projectRoot '.runtime'
} else {
    [IO.Path]::GetFullPath($RuntimeDirectory)
}
$credentialPath = Join-Path $runtimeDirectory 'libreclinica-soap-credentials.json'
$encryptedLoginPath = Join-Path $runtimeDirectory 'libreclinica-login.dpapi.json'
$soapUsername = 'companion_soap'
$browserUsername = 'sandbox_admin'
$predefinedAccounts = @('sandbox_admin', 'site_a_investigator', 'companion_soap')

function Set-CurrentUserOnlyAcl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $Path '/inheritance:r' '/grant:r' "${identity}:(R,W)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The local credential was written but its Windows ACL could not be restricted: $Path"
    }
}

function Get-RandomLocalPassword {
    $bytes = New-Object byte[] 24
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    return ([Convert]::ToBase64String($bytes).TrimEnd('=') -replace '[+/]', 'A') + '!7a'
}

function Get-Sha1Hex {
    param([Parameter(Mandatory = $true)][string]$Value)
    $sha1 = [Security.Cryptography.SHA1]::Create()
    try {
        $passwordBytes = [Text.Encoding]::UTF8.GetBytes($Value)
        return [BitConverter]::ToString($sha1.ComputeHash($passwordBytes)).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha1.Dispose()
    }
}

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$plainPassword = $null
$passwordSha1 = $null
if ($ApplyExisting) {
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) {
        throw 'The localhost LibreClinica SOAP credential file is missing.'
    }
    $stored = Get-Content -LiteralPath $credentialPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($stored.username -ne $soapUsername -or $stored.password_sha1 -notmatch '^[0-9a-f]{40}$') {
        throw 'The localhost LibreClinica SOAP credential file is invalid.'
    }
    $passwordSha1 = $stored.password_sha1
} else {
    if ($GenerateLocalPassword) {
        $plainPassword = Get-RandomLocalPassword
    } else {
        $securePassword = Read-Host -Prompt 'Enter a new localhost LibreClinica password' -AsSecureString
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        try {
            $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        } finally {
            if ($passwordPointer -ne [IntPtr]::Zero) {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
            }
            $securePassword = $null
        }
    }
    if ([string]::IsNullOrWhiteSpace($plainPassword) -or $plainPassword.Length -lt 12) {
        throw 'The LibreClinica password must contain at least 12 characters.'
    }
    $passwordSha1 = Get-Sha1Hex -Value $plainPassword
    $payload = [ordered]@{ username = $soapUsername; password_sha1 = $passwordSha1 } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($credentialPath, $payload, (New-Object Text.UTF8Encoding($false)))
    Set-CurrentUserOnlyAcl -Path $credentialPath

    $secureForDpapi = ConvertTo-SecureString -String $plainPassword -AsPlainText -Force
    $encryptedLogin = [ordered]@{
        username = $browserUsername
        encrypted_password = ConvertFrom-SecureString -SecureString $secureForDpapi
    } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($encryptedLoginPath, $encryptedLogin, (New-Object Text.UTF8Encoding($false)))
    Set-CurrentUserOnlyAcl -Path $encryptedLoginPath
}

if (-not [string]::IsNullOrWhiteSpace($DatabaseContainer)) {
    if ($DatabaseContainer -notmatch '^[0-9a-f]{12,64}$') {
        throw 'The portable PostgreSQL container identifier is invalid.'
    }
    if ($passwordSha1 -notmatch '^[0-9a-f]{40}$') {
        throw 'The password digest is invalid.'
    }
    $accountList = ($predefinedAccounts | ForEach-Object { "'$_'" }) -join ', '
    $sql = @"
UPDATE user_account
SET passwd = '$passwordSha1',
    enabled = true,
    account_non_locked = true,
    lock_counter = 0,
    date_updated = now()
WHERE user_name IN ($accountList);
SELECT count(*) FROM user_account WHERE user_name IN ($accountList) AND passwd = '$passwordSha1';
"@
    $psqlOutput = @($sql | & docker exec -i $DatabaseContainer psql -U clinica -d libreclinica -v ON_ERROR_STOP=1 -A -t)
    $updatedCount = ($psqlOutput | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or $updatedCount -ne "$($predefinedAccounts.Count)") {
        throw 'The predefined localhost LibreClinica accounts were not updated.'
    }
}

Write-Output 'PASS: localhost LibreClinica accounts are configured for this Windows account.'
if (-not $ApplyExisting -and -not $SuppressPasswordDisplay) {
    Write-Host "LibreClinica username: $browserUsername"
    Write-Host "LibreClinica password: $plainPassword"
    Write-Host 'This password is encrypted with Windows DPAPI. Run Show-LibreClinica-Login.cmd to display it again.'
}
$plainPassword = $null
$passwordSha1 = $null
