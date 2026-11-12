param(
    [ValidateSet('Install','Uninstall','Status','Stop')][string]$Action = 'Status',
    [string]$Config = 'D:\CGKN\.cgkn\network-watchdog\watchdog-config.json',
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$taskName = 'CGKN-API-Network-Watchdog'
if ($Action -eq 'Install') {
    if (-not $Python) { $Python = (Get-Command python).Source }
    $resolvedConfig = (Resolve-Path -LiteralPath $Config).Path
    $workspace = Split-Path -Parent $PSScriptRoot
    $arguments = '-X utf8 -m scripts.network_watchdog run --config "' + $resolvedConfig + '"'
    $taskAction = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $workspace
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Description 'CGKN dedicated API network supervisor' -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
} elseif ($Action -eq 'Uninstall') {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
} elseif ($Action -eq 'Stop') {
    if (-not $Python) { $Python = (Get-Command python).Source }
    & $Python -X utf8 -m scripts.network_watchdog stop --config $Config
} else {
    Get-ScheduledTask -TaskName $taskName
    Get-ScheduledTaskInfo -TaskName $taskName
}
