function Get-NullableWindowsFeatureState {
    param([Parameter(Mandatory = $true)][string]$FeatureName)
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $FeatureName -ErrorAction Stop
        return $feature.State -eq 'Enabled'
    } catch {
        return $null
    }
}

function Invoke-DockerInfoProbe {
    param([Parameter(Mandatory = $true)][string]$DockerExecutable)
    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    try {
        $process = Start-Process `
            -FilePath $DockerExecutable `
            -ArgumentList @('info', '--format', '{{.ServerVersion}}') `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -NoNewWindow `
            -Wait `
            -PassThru
        $dockerOutput = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
        } else { '' }
        $ready = $process.ExitCode -eq 0
        $category = if ($ready) {
            $null
        } elseif ($dockerOutput -match '(?i)(dockerDesktopLinuxEngine|pipe|500 Internal Server Error)') {
            'engine_pipe_unavailable'
        } else {
            'engine_unavailable'
        }
        return [pscustomobject]@{ ready = $ready; error_category = $category }
    } finally {
        foreach ($path in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Invoke-PortableProcessQuiet {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )
    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    try {
        try {
            $ErrorActionPreference = 'Continue'
            & $FilePath @ArgumentList 1> $stdoutPath 2> $stderrPath
            $exitCode = $LASTEXITCODE
            return [pscustomobject]@{
                exit_code = [int]$exitCode
                error_category = if ($exitCode -eq 0) { $null } else { 'process_nonzero_exit' }
            }
        } catch {
            return [pscustomobject]@{
                exit_code = 127
                error_category = 'process_launch_failed'
            }
        }
    } finally {
        foreach ($path in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Get-DockerExecutablePath {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe')
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\resources\bin\docker.exe')
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates += (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function Get-DockerDesktopExecutablePath {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
        $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe')
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates += (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function Invoke-DockerDesktopStart {
    param([Parameter(Mandatory = $true)][string]$DockerExecutable)

    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    try {
        try {
            $process = Start-Process `
                -FilePath $DockerExecutable `
                -ArgumentList @('desktop', 'start', '--detach') `
                -RedirectStandardOutput $stdoutPath `
                -RedirectStandardError $stderrPath `
                -NoNewWindow `
                -PassThru `
                -ErrorAction Stop
            $cliExited = $process.WaitForExit(30000)
            if (-not $cliExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
            if ($cliExited -and $process.ExitCode -eq 0) {
                return [pscustomobject]@{
                    started = $true
                    method = 'desktop_cli'
                    error_category = $null
                }
            }
        } catch {}
    } finally {
        foreach ($path in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if ($null -ne (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        return [pscustomobject]@{
            started = $false
            method = 'existing_process'
            error_category = $null
        }
    }

    $desktopExecutable = Get-DockerDesktopExecutablePath
    if ([string]::IsNullOrWhiteSpace($desktopExecutable)) {
        return [pscustomobject]@{
            started = $false
            method = 'unavailable'
            error_category = 'desktop_executable_missing'
        }
    }
    try {
        Start-Process -FilePath $desktopExecutable -ErrorAction Stop | Out-Null
        $isPerUserInstall = -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA) -and `
            $desktopExecutable.StartsWith($env:LOCALAPPDATA, [StringComparison]::OrdinalIgnoreCase)
        $method = if ($isPerUserInstall) {
            'per_user_executable'
        } else {
            'all_users_executable'
        }
        return [pscustomobject]@{
            started = $true
            method = $method
            error_category = $null
        }
    } catch {
        return [pscustomobject]@{
            started = $false
            method = 'unavailable'
            error_category = 'desktop_start_failed'
        }
    }
}

function Start-DockerDesktopAndWait {
    param(
        [Parameter(Mandatory = $true)][string]$DockerExecutable,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 180,
        [ValidateRange(1, 10000)][int]$PollMilliseconds = 3000,
        [scriptblock]$Probe,
        [scriptblock]$StartAction
    )

    if ($null -eq $Probe) {
        $dockerPathForProbe = $DockerExecutable
        $Probe = { Invoke-DockerInfoProbe -DockerExecutable $dockerPathForProbe }.GetNewClosure()
    }
    $initialProbe = & $Probe
    if ($initialProbe.ready) {
        return [pscustomobject]@{
            ready = $true
            attempted = $false
            method = 'none'
            outcome = 'already_ready'
            wait_seconds = 0
            error_category = $null
        }
    }
    if ($null -eq $StartAction) {
        $dockerPathForStart = $DockerExecutable
        $StartAction = { Invoke-DockerDesktopStart -DockerExecutable $dockerPathForStart }.GetNewClosure()
    }

    $startResult = & $StartAction
    if ($startResult.method -eq 'unavailable') {
        return [pscustomobject]@{
            ready = $false
            attempted = $true
            method = 'unavailable'
            outcome = 'launch_failed'
            wait_seconds = 0
            error_category = $startResult.error_category
        }
    }

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $nextProgressSecond = 15
    do {
        $currentProbe = & $Probe
        if ($currentProbe.ready) {
            $stopwatch.Stop()
            return [pscustomobject]@{
                ready = $true
                attempted = $true
                method = $startResult.method
                outcome = 'ready'
                wait_seconds = [Math]::Min($TimeoutSeconds, [Math]::Ceiling($stopwatch.Elapsed.TotalSeconds))
                error_category = $null
            }
        }
        if ($stopwatch.Elapsed.TotalSeconds -ge $TimeoutSeconds) { break }
        if ($stopwatch.Elapsed.TotalSeconds -ge $nextProgressSecond) {
            Write-Host "INFO: Waiting for Docker Desktop Linux engine ($nextProgressSecond seconds)..."
            $nextProgressSecond += 15
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    } while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds)
    $stopwatch.Stop()

    return [pscustomobject]@{
        ready = $false
        attempted = $true
        method = $startResult.method
        outcome = 'timeout'
        wait_seconds = $TimeoutSeconds
        error_category = $currentProbe.error_category
    }
}

function Get-PortableHostState {
    $processors = @()
    $computerSystem = $null
    $operatingSystem = $null
    try { $processors = @(Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop) } catch {}
    try { $computerSystem = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop } catch {}
    try { $operatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop } catch {}

    $virtualizationFirmwareEnabled = if ($processors.Count -gt 0) {
        @($processors | Where-Object { $_.VirtualizationFirmwareEnabled -eq $true }).Count -gt 0
    } else { $null }
    $slatSupported = if ($processors.Count -gt 0) {
        @($processors | Where-Object { $_.SecondLevelAddressTranslationExtensions -eq $true }).Count -gt 0
    } else { $null }
    $hypervisorPresent = if ($null -ne $computerSystem) {
        [bool]$computerSystem.HypervisorPresent
    } else { $null }
    $machineText = if ($null -ne $computerSystem) {
        "$($computerSystem.Manufacturer) $($computerSystem.Model)"
    } else { '' }
    $isVirtualMachine = $machineText -match '(?i)(virtual machine|vmware|virtualbox|kvm|qemu|xen|parallels|hyper-v)'

    $wslCommand = Get-Command wsl.exe -ErrorAction SilentlyContinue
    $wslAvailable = $null -ne $wslCommand
    $wslVersion = $null
    if ($wslAvailable) {
        $wslVersionOutput = @(& wsl.exe --version 2>$null) -join "`n"
        if ($wslVersionOutput -match '(?m)(\d+\.\d+\.\d+(?:\.\d+)?)') {
            $wslVersion = $Matches[1]
        }
    }

    $dockerExecutable = Get-DockerExecutablePath
    $dockerInstalled = -not [string]::IsNullOrWhiteSpace($dockerExecutable)
    $dockerEngineReady = $false
    $dockerErrorCategory = $null
    if ($dockerInstalled) {
        $dockerProbe = Invoke-DockerInfoProbe -DockerExecutable $dockerExecutable
        $dockerEngineReady = $dockerProbe.ready
        $dockerErrorCategory = $dockerProbe.error_category
    }

    [pscustomobject]@{
        virtualization_firmware_enabled = $virtualizationFirmwareEnabled
        hypervisor_present = $hypervisorPresent
        slat_supported = $slatSupported
        is_virtual_machine = [bool]$isVirtualMachine
        virtual_machine_platform_enabled = Get-NullableWindowsFeatureState -FeatureName 'VirtualMachinePlatform'
        wsl_feature_enabled = Get-NullableWindowsFeatureState -FeatureName 'Microsoft-Windows-Subsystem-Linux'
        wsl_available = [bool]$wslAvailable
        wsl_version = $wslVersion
        docker_installed = [bool]$dockerInstalled
        docker_engine_ready = [bool]$dockerEngineReady
        docker_error_category = $dockerErrorCategory
        windows_product_type = if ($null -ne $operatingSystem) { [int]$operatingSystem.ProductType } else { $null }
        windows_caption = if ($null -ne $operatingSystem) { [string]$operatingSystem.Caption } else { $null }
        windows_build = if ($null -ne $operatingSystem) { [string]$operatingSystem.BuildNumber } else { $null }
    }
}

function Resolve-PortableHostDiagnostic {
    param([Parameter(Mandatory = $true)]$State)

    $virtualizationReady = $State.virtualization_firmware_enabled -eq $true -or $State.hypervisor_present -eq $true
    if (-not $virtualizationReady -and $State.is_virtual_machine -eq $true) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-NESTED-VIRTUALIZATION-REQUIRED'
            summary = '当前 Windows 位于虚拟机或 VDI 中，但宿主机未向该虚拟机开放嵌套虚拟化。'
            steps = @('联系 IT 或宿主机管理员启用 nested virtualization。', '完成后重启此 Windows，再启动 Docker Desktop。')
            requires_reboot = $true
            requires_firmware_or_host_change = $true
        }
    }
    if (-not $virtualizationReady) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-VIRTUALIZATION-DISABLED'
            summary = '未检测到可用的硬件虚拟化；Docker Desktop 的 Linux 引擎无法启动。'
            steps = @('打开任务管理器 -> 性能 -> CPU，确认“虚拟化”为“已启用”。', '若为“已禁用”，进入 BIOS/UEFI，启用 Intel Virtualization Technology/VT-x 或 AMD SVM Mode。', '保存设置并完全重启 Windows，然后再次启动 Docker Desktop。')
            requires_reboot = $true
            requires_firmware_or_host_change = $true
        }
    }
    if ($State.slat_supported -eq $false -and $State.hypervisor_present -ne $true) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-SLAT-UNSUPPORTED'
            summary = '处理器未报告 WSL2 所需的二级地址转换（SLAT）支持。'
            steps = @('确认 BIOS/UEFI 虚拟化已启用。', '若仍不支持，需要更换支持 SLAT 的电脑。')
            requires_reboot = $false
            requires_firmware_or_host_change = $true
        }
    }
    if ($null -ne $State.windows_product_type -and $State.windows_product_type -ne 1) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-WINDOWS-SERVER-UNSUPPORTED'
            summary = 'Docker Desktop 不支持当前 Windows Server 系统。'
            steps = @('请改用受支持的 Windows 10/11 工作站，或由 IT 提供受支持的容器主机。')
            requires_reboot = $false
            requires_firmware_or_host_change = $true
        }
    }
    if ($State.virtual_machine_platform_enabled -eq $false) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-VIRTUAL-MACHINE-PLATFORM-DISABLED'
            summary = 'Windows 的 Virtual Machine Platform 功能未启用。'
            steps = @('以管理员身份运行 Repair-Docker-Prerequisites.cmd。', '完成后必须重启 Windows。')
            requires_reboot = $true
            requires_firmware_or_host_change = $false
        }
    }
    if ($State.wsl_feature_enabled -eq $false -or $State.wsl_available -eq $false) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-WSL2-UNAVAILABLE'
            summary = 'WSL2 未安装、未启用或尚未完成重启。'
            steps = @('以管理员身份运行 Repair-Docker-Prerequisites.cmd。', '完成后重启 Windows，再运行 wsl --update。')
            requires_reboot = $true
            requires_firmware_or_host_change = $false
        }
    }
    if ($State.docker_installed -eq $false) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-DOCKER-DESKTOP-MISSING'
            summary = '未安装 Docker Desktop。'
            steps = @('运行 Install-Docker-Desktop.cmd，从 Docker 官方页面安装 WSL2 版本。', '接受许可并启动 Docker Desktop。')
            requires_reboot = $false
            requires_firmware_or_host_change = $false
        }
    }
    if ($State.docker_engine_ready -eq $false) {
        return [pscustomobject]@{
            ready = $false
            code = 'EDC-HOST-DOCKER-ENGINE-NOT-READY'
            summary = 'Docker Desktop 已安装，但 Linux 引擎尚未就绪。'
            steps = @('启动器已尝试启动 Docker Desktop；请查看可见窗口并完成首次许可确认。', '若刚启用 WSL2 或虚拟化，请先重启 Windows，再运行 Start-Clinical-EDC.cmd。', '仍失败时运行 Diagnose-This-PC.cmd 并将生成的诊断 JSON 交给维护人员。')
            requires_reboot = $false
            requires_firmware_or_host_change = $false
        }
    }
    return [pscustomobject]@{
        ready = $true
        code = 'EDC-HOST-READY'
        summary = 'Windows、WSL2 与 Docker Desktop 已满足启动要求。'
        steps = @()
        requires_reboot = $false
        requires_firmware_or_host_change = $false
    }
}

function Write-PortableHostDiagnostic {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)]$Diagnostic,
        [Parameter(Mandatory = $true)][string]$Path,
        $DockerStartResult
    )
    $payload = [ordered]@{
        checked_at = (Get-Date).ToUniversalTime().ToString('o')
        code = $Diagnostic.code
        ready = $Diagnostic.ready
        summary = $Diagnostic.summary
        steps = $Diagnostic.steps
        requires_reboot = $Diagnostic.requires_reboot
        requires_firmware_or_host_change = $Diagnostic.requires_firmware_or_host_change
        capabilities = [ordered]@{
            virtualization_firmware_enabled = $State.virtualization_firmware_enabled
            hypervisor_present = $State.hypervisor_present
            slat_supported = $State.slat_supported
            is_virtual_machine = $State.is_virtual_machine
            virtual_machine_platform_enabled = $State.virtual_machine_platform_enabled
            wsl_feature_enabled = $State.wsl_feature_enabled
            wsl_available = $State.wsl_available
            wsl_version = $State.wsl_version
            docker_installed = $State.docker_installed
            docker_engine_ready = $State.docker_engine_ready
            docker_error_category = $State.docker_error_category
            windows_product_type = $State.windows_product_type
            windows_caption = $State.windows_caption
            windows_build = $State.windows_build
        }
    }
    if ($null -ne $DockerStartResult) {
        $allowedMethods = @('none', 'existing_process', 'desktop_cli', 'per_user_executable', 'all_users_executable', 'unavailable')
        $allowedOutcomes = @('already_ready', 'ready', 'launch_failed', 'timeout')
        $safeMethod = if ($allowedMethods -contains $DockerStartResult.method) { $DockerStartResult.method } else { 'unavailable' }
        $safeOutcome = if ($allowedOutcomes -contains $DockerStartResult.outcome) { $DockerStartResult.outcome } else { 'launch_failed' }
        $safeWaitSeconds = [Math]::Max(0, [Math]::Min(600, [int]$DockerStartResult.wait_seconds))
        $payload['docker_start'] = [ordered]@{
            attempted = [bool]$DockerStartResult.attempted
            method = $safeMethod
            outcome = $safeOutcome
            wait_seconds = $safeWaitSeconds
        }
    }
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [IO.File]::WriteAllText($Path, ($payload | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
}

function Show-PortableHostDiagnostic {
    param([Parameter(Mandatory = $true)]$Diagnostic)
    Write-Host "[$($Diagnostic.code)] $($Diagnostic.summary)"
    $stepNumber = 1
    foreach ($step in $Diagnostic.steps) {
        Write-Host "$stepNumber. $step"
        $stepNumber += 1
    }
}

function Assert-PortableHostReady {
    param(
        [Parameter(Mandatory = $true)][string]$ReportPath,
        [switch]$OpenDockerInstallPage,
        $DockerStartResult
    )
    $state = Get-PortableHostState
    $diagnostic = Resolve-PortableHostDiagnostic -State $state
    Write-PortableHostDiagnostic -State $state -Diagnostic $diagnostic -Path $ReportPath -DockerStartResult $DockerStartResult
    if (-not $diagnostic.ready) {
        Show-PortableHostDiagnostic -Diagnostic $diagnostic
        if ($OpenDockerInstallPage -and $diagnostic.code -eq 'EDC-HOST-DOCKER-DESKTOP-MISSING') {
            Start-Process 'https://docs.docker.com/desktop/setup/install/windows-install/'
        }
        throw "Portable host preflight failed: $($diagnostic.code)"
    }
    return $diagnostic
}
