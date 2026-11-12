param(
    [Parameter(Mandatory=$true)][string]$LibraryRoot,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$PythonArguments
)
$env:VERIARBOR_EDITABLE_SITE = Join-Path $LibraryRoot '.venv\Lib\site-packages'
$env:PYTHONPATH = (Join-Path $PSScriptRoot 'bootstrap') + [IO.Path]::PathSeparator + $env:PYTHONPATH
$env:PYTHONDONTWRITEBYTECODE = '1'
& $Python @PythonArguments
exit $LASTEXITCODE
