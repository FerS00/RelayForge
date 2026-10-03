param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Logon', 'StartupS4U', 'StartupPassword')]
    [string]$Mode,
    [switch]$Deep,
    [string]$GitRemote,
    [string]$GitPushRemote
)

$ErrorActionPreference = 'Stop'
$taskName = "RelayForge-POC10-$Mode"
$pythonPath = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
$probe = Join-Path $PSScriptRoot 'probe.py'
$workingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Write-Error "No se encontró el intérprete del entorno pocs: $pythonPath"
    exit 2
}
$python = (Resolve-Path -LiteralPath $pythonPath).Path
foreach ($remoteValue in @($GitRemote, $GitPushRemote)) {
    if ($remoteValue -and ($remoteValue.Contains('"') -or $remoteValue.Contains("`r") -or $remoteValue.Contains("`n"))) {
        Write-Error 'Las URL Git no pueden contener comillas ni saltos de línea.'
        exit 2
    }
}
if ($Mode -eq 'StartupS4U') {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error 'StartupS4U requiere una consola elevada. Ejecuta PowerShell como administrador.'
        exit 2
    }
}

$arguments = @('-X', 'utf8', "`"$probe`"", '--label', $Mode)
if ($Deep) { $arguments += '--deep' }
if ($GitRemote) { $arguments += @('--git-remote-check', "`"$GitRemote`"") }
if ($GitPushRemote) { $arguments += @('--git-push-check', "`"$GitPushRemote`"") }
$action = New-ScheduledTaskAction -Execute $python -Argument ($arguments -join ' ') -WorkingDirectory $workingDirectory
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

switch ($Mode) {
    'Logon' {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $taskPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
            -Principal $taskPrincipal -Settings $settings -Force | Out-Null
    }
    'StartupS4U' {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $taskPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
            -Principal $taskPrincipal -Settings $settings -Force | Out-Null
    }
    'StartupPassword' {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $credential = Get-Credential -UserName $user -Message 'Credencial para RelayForge POC-10'
        if ($null -eq $credential -or $credential.UserName -ne $user) {
            Write-Error 'Introduce la contraseña del usuario actual.'
            exit 2
        }
        $password = $credential.GetNetworkCredential().Password
        try {
            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
                -User $user -Password $password -Settings $settings -Force | Out-Null
        }
        finally {
            Remove-Variable password -ErrorAction SilentlyContinue
            $credential = $null
        }
    }
}

Write-Output "Tarea registrada: $taskName"
