param(
    [string]$ChatId = "",
    [string]$Model = "",
    [int]$GenerationTimeout = 900,
    [ValidateSet("observe", "gate")]
    [string]$SupervisionPolicy = "gate"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$profileRoot = Join-Path $repoRoot "generated\cgkn_editions\codex"
$stateDir = Join-Path $repoRoot ".cgkn\editions\codex"
$launchArgs = @(
    "-m", "scripts.cgkn_runtime_supervisor", "run",
    "--start-telegram",
    "--generation-mode", "api",
    "--generation-timeout", "$GenerationTimeout",
    "--supervision-policy", $SupervisionPolicy,
    "--state-dir", $stateDir,
    "--session-dir", (Join-Path $profileRoot "sessions"),
    "--log-dir", (Join-Path $profileRoot "logs"),
    "--upload-dir", (Join-Path $profileRoot "uploads"),
    "--memory-dir", (Join-Path $profileRoot "memory"),
    "--provider-projects-dir", (Join-Path $profileRoot "provider_projects")
)
if ($ChatId) {
    $launchArgs += @("--chat-id", $ChatId)
}
if ($Model) {
    $launchArgs += @("--model", $Model)
}

Push-Location $repoRoot
try {
    & python @launchArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CGKN Codex Edition exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
