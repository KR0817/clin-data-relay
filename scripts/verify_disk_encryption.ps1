param(
    [ValidatePattern('^[A-Za-z]:$')][string]$Volume = 'C:'
)

$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this read-only verification script from an elevated PowerShell window.'
}

$output = & manage-bde.exe -status $Volume 2>&1
if ($LASTEXITCODE -ne 0) {
    throw (($output -join "`n").Trim())
}

$text = ($output -join "`n")
$lower = $text.ToLowerInvariant()
# Keep this script ASCII-only: Windows PowerShell 5.1 may parse a UTF-8 file
# using the active code page. Build the localized marker at runtime instead.
$protectionEnabledMarker = [string]::Concat([char]0x4fdd, [char]0x62a4, [char]0x5df2, [char]0x542f, [char]0x7528)
$fullyEncrypted = $lower.Contains('fully encrypted') -or ($lower -match '100\.0\s*%')
$protectionOn = ($lower.Contains('protection status') -and $lower.Contains('protection on')) -or $lower.Contains($protectionEnabledMarker)
[pscustomobject]@{
    volume = $Volume.ToUpperInvariant()
    status = if ($fullyEncrypted -and $protectionOn) { 'enabled' } else { 'not_fully_enabled' }
    raw_status = $text
} | ConvertTo-Json -Depth 3
