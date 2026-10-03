param(
    [ValidateSet('Logon', 'StartupS4U', 'StartupPassword')]
    [string]$Mode,
    [switch]$All
)

$ErrorActionPreference = 'Stop'
if ($All -and $Mode) {
    Write-Error 'Usa -All o -Mode, no ambos.'
    exit 2
}
if (-not $All -and -not $Mode) {
    Write-Error 'Indica -Mode Logon|StartupS4U|StartupPassword o -All.'
    exit 2
}

if ($All) {
    $tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like 'RelayForge-POC10-*' }
}
else {
    $tasks = Get-ScheduledTask -TaskName "RelayForge-POC10-$Mode" -ErrorAction SilentlyContinue
}

foreach ($task in $tasks) {
    Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Confirm:$false
    Write-Output "Tarea eliminada: $($task.TaskName)"
}
if (-not $tasks) { Write-Output 'No se encontraron tareas RelayForge-POC10.' }
