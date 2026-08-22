[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'This repair must run as Administrator.'
}

foreach ($feature in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
    & dism.exe /online /enable-feature "/featurename:$feature" /all /norestart
    if ($LASTEXITCODE -notin @(0, 3010)) {
        throw "Could not enable Windows feature: $feature"
    }
}
& bcdedit.exe /set hypervisorlaunchtype auto | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Could not enable the Windows hypervisor at startup.'
}
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    & wsl.exe --update
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'WSL update did not complete. Run wsl --update after restarting Windows.'
    }
}
Write-Output 'PASS: WSL and Virtual Machine Platform prerequisites are enabled.'
Write-Output 'Restart Windows now. BIOS/UEFI virtualization must still be enabled separately.'
