$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$config = Join-Path $PSScriptRoot "telegram_new_config.example.json"

if (-not $env:TELEGRAM_BOT_TOKEN) {
  Write-Error "Set TELEGRAM_BOT_TOKEN before starting the listener."
}

if (-not $env:TELEGRAM_ADMIN_IDS) {
  Write-Error "Set TELEGRAM_ADMIN_IDS before starting the listener. Example: `$env:TELEGRAM_ADMIN_IDS='123456789'"
}

Set-Location $root
python scripts/telegram_new_listener.py --config $config
