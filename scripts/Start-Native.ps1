param(
    [Parameter(Mandatory=$true)][string]$WorkspaceDir,
    [Parameter(Mandatory=$true)][string]$DataDir,
    [ValidateRange(1024,65535)][int]$Port = 8876,
    [string]$AuditRunner = "",
    [string]$AllowedHosts = "",
    [string]$AllowedLogins = "",
    [string]$PreviewPublicOrigin = "",
    [switch]$AllowResume
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$workspacePath = (Resolve-Path -LiteralPath $WorkspaceDir).Path
$dataPath = [IO.Path]::GetFullPath($DataDir)
if ($dataPath -eq $workspacePath) { throw 'DataDir debe ser distinto de WorkspaceDir.' }
if ((Test-Path -LiteralPath (Join-Path $dataPath 'relayforge.db')) -and -not $AllowResume) {
    # If the database already belongs to this exact staging dir, allow starting/resuming it
    Write-Host "Reanudando base de datos existente en $dataPath"
}
$env:RELAYFORGE_HOME = $dataPath
$env:RELAYFORGE_WORKSPACE_DIR = $workspacePath
$env:RELAYFORGE_PORT = [string]$Port
$env:RELAYFORGE_BIND = '127.0.0.1'
$env:RELAYFORGE_CONTAINER_MODE = 'false'
$env:RELAYFORGE_TRUSTED_PROXY_IP = ''
$env:RELAYFORGE_CHAT_AGENT = 'codex'
$env:RELAYFORGE_CHAT_MODEL = 'gpt-6-luna'
$env:RELAYFORGE_CHAT_EFFORT = 'medium'
# Identity values are operator-specific: pass them as parameters or environment variables
# (for example from an untracked scripts/Start-Native.local.ps1); never hard-code them here.
if ($AllowedHosts) { $env:RELAYFORGE_ALLOWED_HOSTS = $AllowedHosts }
if ($AllowedLogins) { $env:RELAYFORGE_ALLOWED_TAILSCALE_LOGINS = $AllowedLogins }
if ($PreviewPublicOrigin) { $env:RELAYFORGE_PREVIEW_PUBLIC_ORIGIN = $PreviewPublicOrigin }
if (-not $env:RELAYFORGE_ALLOWED_HOSTS -or -not $env:RELAYFORGE_ALLOWED_TAILSCALE_LOGINS) {
    throw 'Indica -AllowedHosts y -AllowedLogins (o RELAYFORGE_ALLOWED_HOSTS y RELAYFORGE_ALLOWED_TAILSCALE_LOGINS).'
}
if ($AuditRunner) {
    $env:RELAYFORGE_ANTIGRAVITY_AUDIT_RUNNER = (Resolve-Path -LiteralPath $AuditRunner).Path
}
& uv run --directory $repoRoot relayforge serve
exit $LASTEXITCODE
