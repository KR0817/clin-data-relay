[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('virtualization_disabled_with_docker_named_pipe_500', 'nested_virtualization_required', 'docker_named_pipe_stderr_capture', 'native_nonzero_is_nonterminating', 'active_hypervisor_with_ambiguous_slat', 'docker_engine_autostart_ready', 'docker_engine_autostart_timeout', 'ready')]
    [string]$Scenario
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'portable_host_preflight.ps1')

if ($Scenario -eq 'native_nonzero_is_nonterminating') {
    $fakeProcessPath = Join-Path ([IO.Path]::GetTempPath()) "clinical-edc-fake-process-$([Guid]::NewGuid().ToString('N')).cmd"
    try {
        [IO.File]::WriteAllText(
            $fakeProcessPath,
            "@echo off`r`necho expected missing artifact 1>&2`r`nexit /b 1`r`n",
            [Text.Encoding]::ASCII
        )
        $result = Invoke-PortableProcessQuiet -FilePath $fakeProcessPath -ArgumentList @('image', 'inspect', 'missing-image')
        if ($result.exit_code -ne 1) {
            throw 'Expected non-zero native exit code was not preserved.'
        }
        Write-Output 'PASS: EDC-HOST-NATIVE-NONZERO-CAPTURED'
        exit 0
    } finally {
        if (Test-Path -LiteralPath $fakeProcessPath -PathType Leaf) {
            Remove-Item -LiteralPath $fakeProcessPath -Force
        }
    }
}

if ($Scenario -eq 'docker_engine_autostart_ready') {
    $script:dockerProbeCount = 0
    $script:dockerStartCount = 0
    $result = Start-DockerDesktopAndWait `
        -DockerExecutable 'docker.exe' `
        -TimeoutSeconds 2 `
        -PollMilliseconds 1 `
        -Probe {
            $script:dockerProbeCount += 1
            [pscustomobject]@{
                ready = $script:dockerProbeCount -ge 2
                error_category = if ($script:dockerProbeCount -ge 2) { $null } else { 'engine_pipe_unavailable' }
            }
        } `
        -StartAction {
            $script:dockerStartCount += 1
            [pscustomobject]@{ started = $true; method = 'desktop_cli'; error_category = $null }
        }
    if (-not $result.ready -or -not $result.attempted -or $result.method -ne 'desktop_cli') {
        throw 'Docker Desktop auto-start did not reach the ready state.'
    }
    if ($script:dockerStartCount -ne 1 -or $script:dockerProbeCount -lt 2) {
        throw 'Docker Desktop auto-start did not launch once and poll for readiness.'
    }
    Write-Output 'PASS: EDC-HOST-DOCKER-AUTOSTART-READY'
    exit 0
}

if ($Scenario -eq 'docker_engine_autostart_timeout') {
    $script:dockerStartCount = 0
    $result = Start-DockerDesktopAndWait `
        -DockerExecutable 'docker.exe' `
        -TimeoutSeconds 1 `
        -PollMilliseconds 5 `
        -Probe { [pscustomobject]@{ ready = $false; error_category = 'engine_pipe_unavailable' } } `
        -StartAction {
            $script:dockerStartCount += 1
            [pscustomobject]@{ started = $false; method = 'existing_process'; error_category = $null }
        }
    if ($result.ready -or $result.outcome -ne 'timeout' -or $result.wait_seconds -ne 1) {
        throw 'Docker Desktop auto-start timeout did not remain fail-closed.'
    }
    if ($script:dockerStartCount -ne 1) {
        throw 'Docker Desktop timeout scenario launched more than once.'
    }
    Write-Output 'PASS: EDC-HOST-DOCKER-AUTOSTART-TIMEOUT'
    exit 0
}

if ($Scenario -eq 'docker_named_pipe_stderr_capture') {
    $fakeDockerPath = Join-Path ([IO.Path]::GetTempPath()) "clinical-edc-fake-docker-$([Guid]::NewGuid().ToString('N')).cmd"
    try {
        [IO.File]::WriteAllText(
            $fakeDockerPath,
            "@echo off`r`necho request returned 500 Internal Server Error for dockerDesktopLinuxEngine/v1.55/info 1>&2`r`nexit /b 1`r`n",
            [Text.Encoding]::ASCII
        )
        $probe = Invoke-DockerInfoProbe -DockerExecutable $fakeDockerPath
        if ($probe.ready -or $probe.error_category -ne 'engine_pipe_unavailable') {
            throw 'Docker stderr was not reduced to the stable category.'
        }
        Write-Output 'PASS: EDC-HOST-DOCKER-ENGINE-NOT-READY'
        exit 0
    } finally {
        if (Test-Path -LiteralPath $fakeDockerPath -PathType Leaf) {
            Remove-Item -LiteralPath $fakeDockerPath -Force
        }
    }
}

$baseState = [ordered]@{
    virtualization_firmware_enabled = $true
    hypervisor_present = $true
    slat_supported = $true
    is_virtual_machine = $false
    virtual_machine_platform_enabled = $true
    wsl_feature_enabled = $true
    wsl_available = $true
    wsl_version = '2.6.1.0'
    docker_installed = $true
    docker_engine_ready = $true
    docker_error_category = $null
    windows_product_type = 1
    windows_caption = 'Microsoft Windows 11 Pro'
    windows_build = '22631'
}
$expectedCode = 'EDC-HOST-READY'
if ($Scenario -eq 'virtualization_disabled_with_docker_named_pipe_500') {
    $baseState.virtualization_firmware_enabled = $false
    $baseState.hypervisor_present = $false
    $baseState.docker_engine_ready = $false
    $baseState.docker_error_category = 'engine_pipe_unavailable'
    $expectedCode = 'EDC-HOST-VIRTUALIZATION-DISABLED'
} elseif ($Scenario -eq 'nested_virtualization_required') {
    $baseState.virtualization_firmware_enabled = $false
    $baseState.hypervisor_present = $false
    $baseState.is_virtual_machine = $true
    $baseState.docker_engine_ready = $false
    $expectedCode = 'EDC-HOST-NESTED-VIRTUALIZATION-REQUIRED'
} elseif ($Scenario -eq 'active_hypervisor_with_ambiguous_slat') {
    $baseState.virtualization_firmware_enabled = $false
    $baseState.hypervisor_present = $true
    $baseState.slat_supported = $false
    $expectedCode = 'EDC-HOST-READY'
}

$diagnostic = Resolve-PortableHostDiagnostic -State ([pscustomobject]$baseState)
if ($diagnostic.code -ne $expectedCode) {
    throw "Expected $expectedCode but received $($diagnostic.code)."
}
Write-Output "PASS: $($diagnostic.code)"
