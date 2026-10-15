param(
    [string]$RunId = "PGBV1_QWEN_L1_FINAL_REVALIDATION_20261015_01"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$controlRoot = Join-Path $repoRoot "artifacts\project_generation_benchmark\launcher_state"
$workerStatePath = Join-Path $controlRoot "$RunId.worker.json"
$runDir = Join-Path $repoRoot "artifacts\project_generation_benchmark\$RunId"
$worker = if (Test-Path -LiteralPath $workerStatePath) {
    Get-Content -LiteralPath $workerStatePath -Raw | ConvertFrom-Json
} else { $null }
$ledgerPath = Join-Path $runDir "external_api_cost_ledger.json"
$ledger = if (Test-Path -LiteralPath $ledgerPath) {
    Get-Content -LiteralPath $ledgerPath -Raw | ConvertFrom-Json
} else { $null }
$caseResultPath = Join-Path $runDir "cases\CASE_01_CSV_DATA_CLEANER\case_result.json"
$caseResult = if (Test-Path -LiteralPath $caseResultPath) {
    Get-Content -LiteralPath $caseResultPath -Raw | ConvertFrom-Json
} else { $null }
$calls = if ($null -ne $ledger) { @($ledger.calls) } else { @() }
$phaseLog = Get-ChildItem -LiteralPath $runDir -Recurse -Force -File -Filter "provider_phase_log.jsonl" -ErrorAction SilentlyContinue | Select-Object -First 1
$lastPhase = if ($null -ne $phaseLog) { Get-Content -LiteralPath $phaseLog.FullName -Tail 1 } else { "" }

[ordered]@{
    kind = "CGKNQwenL1SmokeReadOnlyStatus"
    schema_version = "1.0"
    run_id = $RunId
    process_status = if ($null -ne $worker) { [string]$worker.state } else { "NOT_STARTED" }
    process_id = if ($null -ne $worker) { $worker.process_id } else { $null }
    current_phase = $lastPhase
    qwen_calls = [ordered]@{
        reserved = @($calls | Where-Object status -eq "RESERVED").Count
        started = @($calls | Where-Object { $_.status -in @("REQUEST_STARTED", "RESPONSE_RECEIVED", "SUCCEEDED", "FAILED", "INTERRUPTED_UNKNOWN") }).Count
        completed = @($calls | Where-Object { $_.status -in @("SUCCEEDED", "FAILED") }).Count
        unknown = @($calls | Where-Object status -eq "INTERRUPTED_UNKNOWN").Count
        planning = @($calls | Where-Object { ([string]$_.purpose).StartsWith("PLANNING") }).Count
        generation = @($calls | Where-Object purpose -eq "GENERATION").Count
        repair = @($calls | Where-Object { ([string]$_.purpose).StartsWith("REPAIR") }).Count
    }
    candidate_status = if ($null -ne $caseResult) { [string]$caseResult.result } else { "NOT_EVALUATED" }
    last_error = if ($null -ne $caseResult) { @($caseResult.hard_failures) | Select-Object -First 1 } elseif ($null -ne $worker) { [string]$worker.error } else { "" }
    read_only = $true
} | ConvertTo-Json -Depth 8
