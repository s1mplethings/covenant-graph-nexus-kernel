param(
    [string]$RunId = "PGBV1_QWEN_L1_FINAL_REVALIDATION_20261015_01",
    [Parameter(Mandatory = $true)]
    [ValidateSet("RUN_QWEN_L1_SMOKE")]
    [string]$Confirmation
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$catalog = Join-Path $repoRoot "benchmarks\project_generation_v1\cases.json"
$expectedCatalogHash = "9B470B65970D6A3A33D45CDCAA4646B785F1F348C27F6121573F23E7D57974AF"
$actualCatalogHash = (Get-FileHash -LiteralPath $catalog -Algorithm SHA256).Hash
if ($actualCatalogHash -ne $expectedCatalogHash) {
    throw "Frozen Fixed10 catalog identity mismatch."
}

$runDir = Join-Path $repoRoot "artifacts\project_generation_benchmark\$RunId"
if (Test-Path -LiteralPath $runDir) {
    throw "Run already exists; use CHECK_QWEN_L1_SMOKE.ps1 instead of starting a duplicate."
}

$controlRoot = Join-Path $repoRoot "artifacts\project_generation_benchmark\launcher_state"
New-Item -ItemType Directory -Path $controlRoot -Force | Out-Null
$configPath = Join-Path $controlRoot "$RunId.config.json"
$workerStatePath = Join-Path $controlRoot "$RunId.worker.json"
$stdoutPath = Join-Path $controlRoot "$RunId.stdout.log"
$stderrPath = Join-Path $controlRoot "$RunId.stderr.log"
$python = "D:\anaconda\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Configured Python interpreter is unavailable."
}

$config = [ordered]@{
    kind = "CGKNQwenL1SmokeLauncherConfig"
    schema_version = "1.0"
    run_id = $RunId
    repo_root = $repoRoot
    python = $python
    worker_state = $workerStatePath
    goal_identity = "sha256:e7e6fb1837f84063a76b1498f3d61f426adca3fcf21ac5886c247b4f96708be8"
    case_id = "CASE_01_CSV_DATA_CLEANER"
    model = "qwen3.6-plus"
    fixed10_sha256 = $actualCatalogHash
    max_total_calls = 4
    max_planning_calls = 1
    max_generation_calls = 1
    max_repair_calls = 2
}
$config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $configPath -Encoding utf8

$worker = Join-Path $repoRoot "scripts\RUN_QWEN_L1_SMOKE_WORKER.ps1"
$process = Start-Process -FilePath "pwsh.exe" -ArgumentList @(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $worker, "-ConfigPath", $configPath
) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru

[ordered]@{
    kind = "CGKNQwenL1SmokeLaunchReceipt"
    schema_version = "1.0"
    run_id = $RunId
    process_id = $process.Id
    process_status = "STARTED"
    worker_state = $workerStatePath
    stdout = $stdoutPath
    stderr = $stderrPath
    secrets_recorded = $false
} | ConvertTo-Json -Depth 5
