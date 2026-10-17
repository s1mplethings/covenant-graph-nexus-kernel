$ErrorActionPreference = "Stop"
$ExtensionRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = Join-Path $ExtensionRoot "src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$SourceRoot;$env:PYTHONPATH" } else { $SourceRoot }
python -m cgkn_provider_lab gui
