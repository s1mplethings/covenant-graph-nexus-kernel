param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$statePath = [string]$config.worker_state
$startedAt = [DateTimeOffset]::UtcNow.ToString("o")

function Write-WorkerState([string]$State, [int]$ExitCode, [string]$ErrorText) {
    [ordered]@{
        kind = "CGKNQwenL1SmokeWorkerState"
        schema_version = "1.0"
        run_id = [string]$config.run_id
        process_id = $PID
        state = $State
        started_at = $startedAt
        updated_at = [DateTimeOffset]::UtcNow.ToString("o")
        exit_code = $ExitCode
        error = $ErrorText
        secrets_recorded = $false
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8
}

Write-WorkerState "RUNNING" -1 ""
try {
    $arguments = @(
        "-m", "benchmarks.project_generation_v1.run_benchmark",
        "--case", [string]$config.case_id,
        "--run-id", [string]$config.run_id,
        "--provider-mode", "live",
        "--model", [string]$config.model,
        "--repair-model", [string]$config.model,
        "--parallelism", "1",
        "--provider-max-retries", "2",
        "--provider-max-tokens", "5000",
        "--provider-temperature", "0.2",
        "--max-api-calls", [string]$config.max_total_calls,
        "--max-planning-calls", [string]$config.max_planning_calls,
        "--max-generation-calls", [string]$config.max_generation_calls,
        "--max-repair-calls", [string]$config.max_repair_calls,
        "--max-total-input-tokens", "120000",
        "--max-total-output-tokens", "30000",
        "--max-estimated-cost", "1",
        "--dependency-mode", "registry",
        "--approve-package-registry",
        "--package-registry-url", "https://pypi.org/simple",
        "--production-timeout", "900",
        "--evaluator-timeout", "600",
        "--repair-timeout", "900"
    )
    & ([string]$config.python) @arguments
    $exitCode = $LASTEXITCODE
    Write-WorkerState ($(if ($exitCode -eq 0) { "COMPLETE" } else { "FAILED" })) $exitCode ""
    exit $exitCode
} catch {
    Write-WorkerState "FAILED" 1 $_.Exception.Message
    exit 1
}
