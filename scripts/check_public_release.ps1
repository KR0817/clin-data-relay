[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
if (-not $repoRoot) {
    throw 'public_release_git_root_not_found'
}

$requiredFiles = @(
    'README.md',
    'README.zh-CN.md',
    'LICENSE',
    'CITATION.cff',
    'CONTRIBUTING.md',
    'SECURITY.md',
    'packaging/SOURCE-CODE.txt',
    'docs/development/ai-assisted-development.md',
    'docs/evaluation/benchmark-protocol-v0.1.md',
    'docs/eval/v1/REPORT.md',
    'docs/eval/v1/protocol.md',
    'docs/eval/v1/reproduce.md',
    'docs/model-provider-configuration.md',
    'app/benchmark_evaluation.py',
    'app/model_provider.py',
    'scripts/evaluate_extraction_benchmark.py',
    'scripts/prepare_benchmark_v1_allocation.py',
    'scripts/generate_benchmark_v1_corpus.py',
    'benchmarks/synthetic-v0.1/manifest.json',
    'benchmarks/synthetic-v0.1/gold.example.jsonl',
    'benchmarks/synthetic-v0.1/local_ocr.example.jsonl',
    'benchmarks/synthetic-v0.1/assisted.example.jsonl',
    'benchmarks/synthetic-v1/dataset-plan.json',
    'benchmarks/synthetic-v1/corpus-freeze.json',
    'benchmarks/synthetic-v1/review-assignments.json',
    'benchmarks/synthetic-v1/manifest.json',
    'benchmarks/synthetic-v1/README.md',
    'docs/releases/v0.2.1.md',
    'docs/releases/v0.3.0.md',
    'docs/assets/architecture.svg',
    'docs/assets/showcase/central-workbench.png',
    'docs/assets/showcase/intake-workflow.png',
    'docs/assets/showcase/review-workflow.png',
    'docs/demo/clin-data-relay-demo.mp4'
)

$failures = [System.Collections.Generic.List[string]]::new()
foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        $failures.Add("missing_required_file:$relativePath")
    }
}

$trackedFiles = @(& git -C $repoRoot ls-files)
$forbiddenPathPattern = '(?i)(^|/)(\.env(?:\..*)?|\.runtime(?:/|$)|[^/]+\.(?:db|db-wal|db-shm|sqlite|sqlite3|key|pem|p12|pfx|log))$'
foreach ($trackedFile in $trackedFiles) {
    if ($trackedFile -match $forbiddenPathPattern) {
        $failures.Add("forbidden_tracked_path:$trackedFile")
    }
}

$textExtensions = @(
    '.cfg', '.cmd', '.css', '.html', '.ini', '.js', '.json', '.md', '.ps1',
    '.py', '.sh', '.toml', '.ts', '.tsx', '.txt', '.xml', '.yaml', '.yml'
)
$secretPatterns = @(
    '-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
    'AKIA[0-9A-Z]{16}',
    'gh[pousr]_[A-Za-z0-9]{20,}',
    'github_pat_[A-Za-z0-9_]{20,}',
    'sk-[A-Za-z0-9_-]{24,}'
)

function Test-ContentForCredentialSignature {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    foreach ($pattern in $secretPatterns) {
        $matches = [regex]::Matches($Content, $pattern)
        $unsafeMatch = $matches | Where-Object {
            $_.Value -notmatch '(?i)(placeholder|example|dummy|test|synthetic|fake)'
        } | Select-Object -First 1
        if ($null -ne $unsafeMatch) {
            return $true
        }
    }
    return $false
}

foreach ($trackedFile in $trackedFiles) {
    $extension = [System.IO.Path]::GetExtension($trackedFile).ToLowerInvariant()
    if ($extension -notin $textExtensions) {
        continue
    }
    $fullPath = Join-Path $repoRoot $trackedFile
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        continue
    }
    $content = Get-Content -LiteralPath $fullPath -Raw
    if (Test-ContentForCredentialSignature -Content $content) {
        $failures.Add("credential_signature:$trackedFile")
    }
}

$historyPathFindings = 0
$historyCredentialFindings = 0
$revisions = @(& git -C $repoRoot rev-list --all)
$historyFiles = @(& git -C $repoRoot log --all --name-only --pretty=format:) |
    Where-Object { $_ } |
    Sort-Object -Unique
foreach ($historyFile in $historyFiles) {
    if ($historyFile -match $forbiddenPathPattern) {
        $historyPathFindings += 1
        $failures.Add("forbidden_history_path:$historyFile")
    }
}

# Scan the complete textual patch history in memory so a credential removed
# from the current tree still blocks publication. Findings never echo values.
$historyPatch = (& git -C $repoRoot log --all -p --no-color --text -- .) -join "`n"
if (Test-ContentForCredentialSignature -Content $historyPatch) {
    $historyCredentialFindings = 1
    $failures.Add('credential_signature_in_history')
}

$readmePath = Join-Path $repoRoot 'README.md'
if (Test-Path -LiteralPath $readmePath -PathType Leaf) {
    $readme = Get-Content -LiteralPath $readmePath -Raw
    foreach ($requiredPhrase in @('research prototype', 'Authority EDC', 'AGPL-3.0-only')) {
        if ($readme -notmatch [regex]::Escape($requiredPhrase)) {
            $failures.Add("readme_boundary_missing:$requiredPhrase")
        }
    }
}

$licensePath = Join-Path $repoRoot 'LICENSE'
if (Test-Path -LiteralPath $licensePath -PathType Leaf) {
    $licenseText = Get-Content -LiteralPath $licensePath -Raw
    foreach ($requiredLicensePhrase in @(
        'GNU AFFERO GENERAL PUBLIC LICENSE',
        'Version 3, 19 November 2007',
        'Remote Network Interaction'
    )) {
        if ($licenseText -notmatch [regex]::Escape($requiredLicensePhrase)) {
            $failures.Add("agpl_text_missing:$requiredLicensePhrase")
        }
    }
}

foreach ($metadataFile in @('pyproject.toml', 'CITATION.cff')) {
    $metadataPath = Join-Path $repoRoot $metadataFile
    if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw
        if ($metadata -notmatch [regex]::Escape('AGPL-3.0-only')) {
            $failures.Add("agpl_metadata_missing:$metadataFile")
        }
    }
}

$videoPath = Join-Path $repoRoot 'docs/demo/clin-data-relay-demo.mp4'
if (Test-Path -LiteralPath $videoPath -PathType Leaf) {
    $videoBytes = (Get-Item -LiteralPath $videoPath).Length
    if ($videoBytes -lt 200000) {
        $failures.Add('demo_video_too_small')
    }
    if ($videoBytes -gt 10MB) {
        $failures.Add('demo_video_exceeds_10_mib')
    }
}

$commitCount = [int](& git -C $repoRoot rev-list --count HEAD)
if ($commitCount -lt 2) {
    $failures.Add('git_history_too_short')
}
$tagCount = @(& git -C $repoRoot tag --list).Count
if ($tagCount -lt 1) {
    $failures.Add('git_tag_missing')
}

if ($failures.Count -gt 0) {
    $failures | Sort-Object -Unique | ForEach-Object { [Console]::Error.WriteLine($_) }
    exit 1
}

[ordered]@{
    status = 'PASS'
    tracked_files = $trackedFiles.Count
    commits = $commitCount
    tags = $tagCount
    demo_video_bytes = (Get-Item -LiteralPath $videoPath).Length
    history_revisions_scanned = $revisions.Count
    history_forbidden_path_findings = $historyPathFindings
    history_credential_findings = $historyCredentialFindings
    secret_values_printed = $false
} | ConvertTo-Json
