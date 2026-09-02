param(
    [string]$ChatId = "",
    [string]$Model = "",
    [int]$GenerationTimeout = 900
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$profileRoot = Join-Path $repoRoot "generated\cgkn_modes\api_only"
$launchArgs = @(
    "-m", "scripts.telegram_live_bridge",
    "--generation-mode", "api",
    "--generation-timeout", "$GenerationTimeout",
    "--codex-design-mode", "disabled",
    "--supervision-policy", "disabled",
    "--runtime-supervisor-dir", "",
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
        throw "CGKN API-only profile exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
