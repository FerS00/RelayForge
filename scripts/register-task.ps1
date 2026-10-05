param(
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$taskName = 'RelayForge'

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Tarea $taskName retirada."
    exit 0
}

$repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$uv = (Get-Command uv -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $uv -Argument "run --directory `"$repository`" relayforge serve" -WorkingDirectory $repository
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'RelayForge local loopback service.' -Force | Out-Null
Write-Output "Tarea $taskName registrada para el inicio de sesión del usuario actual."
