param(
  [string]$Goal = "",
  [string]$Model = "",
  [string]$SmallModel = "",
  [string]$LargeModel = "",
  [switch]$DisableModelRouting,
  [switch]$RequireVideo,
  [int]$Timeout = 900,
  [string]$WorkRoot = "",
  [string]$Report = "",
  [string]$ResumeRunDir = "",
  [string]$Profile = "",
  [ValidateSet("agent-led", "closure")]
  [string]$Mode = "agent-led"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not [string]::IsNullOrWhiteSpace($Profile)) {
  $allowedProfiles = @("quick", "regression", "longrun", "provider", "e2e", "all")
  if ($allowedProfiles -notcontains $Profile) {
    throw "Unknown test profile: $Profile"
  }
  $profileTimeout = if ($Timeout -eq 900) { 300 } else { $Timeout }
  python scripts/run_test_profile.py --profile $Profile --timeout $profileTimeout
  exit $LASTEXITCODE
}

if ([string]::IsNullOrWhiteSpace($env:CGNK_USE_LOCAL_MODEL)) {
  $env:CGNK_USE_LOCAL_MODEL = "1"
}
$requiredLocalTasks = @("pipeline_planner", "cfo_pipeline", "context_support", "risk_support", "foundation", "qa")
if ([string]::IsNullOrWhiteSpace($env:CGNK_LOCAL_MODEL_TASKS)) {
  $env:CGNK_LOCAL_MODEL_TASKS = ($requiredLocalTasks -join ",")
} else {
  $existingLocalTasks = @($env:CGNK_LOCAL_MODEL_TASKS -split "[,;\s]+" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim().ToLowerInvariant() })
  if ($existingLocalTasks -notcontains "all") {
    foreach ($task in $requiredLocalTasks) {
      if ($existingLocalTasks -notcontains $task) {
        $existingLocalTasks += $task
      }
    }
    $env:CGNK_LOCAL_MODEL_TASKS = (($existingLocalTasks | Sort-Object -Unique) -join ",")
  }
}

if ([string]::IsNullOrWhiteSpace($Model)) {
  if ([string]::IsNullOrWhiteSpace($env:CGKN_VERIFY_MODEL)) {
    $Model = "gpt-5.4-nano"
  } else {
    $Model = $env:CGKN_VERIFY_MODEL
  }
}

$entryScript = "scripts/run_agent_led_verify.py"
if ($Mode -eq "closure") {
  $entryScript = "scripts/run_formal_live_delivery_closure.py"
}

$argv = @(
  $entryScript,
  "--model", $Model,
  "--timeout", "$Timeout"
)

if (-not [string]::IsNullOrWhiteSpace($Goal)) {
  $argv += @("--goal", $Goal)
}
if (-not [string]::IsNullOrWhiteSpace($SmallModel)) {
  $argv += @("--small-model", $SmallModel)
}
if (-not [string]::IsNullOrWhiteSpace($LargeModel)) {
  $argv += @("--large-model", $LargeModel)
}
if ($DisableModelRouting) {
  $argv += @("--disable-model-routing")
}
if ($RequireVideo) {
  $argv += @("--require-video")
}
if (-not [string]::IsNullOrWhiteSpace($WorkRoot)) {
  $argv += @("--work-root", $WorkRoot)
}
if (-not [string]::IsNullOrWhiteSpace($Report)) {
  $argv += @("--report", $Report)
}
if (-not [string]::IsNullOrWhiteSpace($ResumeRunDir)) {
  $argv += @("--resume-run-dir", $ResumeRunDir)
}

python @argv
exit $LASTEXITCODE
