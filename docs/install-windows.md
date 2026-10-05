# Instalación en Windows

Esta guía instala RelayForge para el usuario actual. El servicio escucha solo en `127.0.0.1`; el acceso remoto usa Tailscale Serve sobre HTTPS. No se abren puertos en el firewall ni se habilita Funnel.

Para ejecutarlo en Docker Windows, consulta [Docker en Windows](docker-windows.md). Esa opción requiere Docker Desktop en modo all-users y contenedores Windows; en Windows NAT no se publica un puerto de host. Un portproxy Windows escucha solo en loopback y reenvía al contenedor; Tailscale Serve apunta a ese listener loopback, no directamente a la IP NAT.

## Requisitos

- Windows 10/11, Git, Python 3.13+, `uv`, Node.js 20.19+, 22.12+ o 24+ y npm para compilar la interfaz.
- Tailscale iniciado y conectado. Claude Code, Codex y Antigravity CLI instalados y autenticados en el perfil del usuario.
- Un repositorio local confiable; RelayForge ejecuta procesos y herramientas declaradas por sus Jobs.

## Preparación

```powershell
git clone <URL-del-repositorio>
Set-Location RelayForge
uv sync
npm --prefix web ci
npm --prefix web run build
```

En `%LOCALAPPDATA%\RelayForge\config\settings.yaml`, define `workspace_dir` con un directorio existente, `projects_root` con el directorio donde se crearán repositorios nuevos, `allowed_tailscale_logins` con los logins exactos permitidos y `allowed_hosts` con el hostname HTTPS exacto de esta máquina, por ejemplo `laptop.nombre-tailnet.ts.net`. No uses comodines. `bind` solo admite `127.0.0.1`. El archivo de configuración debe existir antes de registrar la tarea para que el servicio reciba las mismas opciones al iniciar sesión.

Ejemplo de configuración sin credenciales:

```yaml
workspace_dir: 'D:\RelayForge-workspace'
projects_root: 'D:\RelayForge-projects'
bind: '127.0.0.1'
port: 8787
allowed_tailscale_logins:
  - 'owner@example.test'
allowed_hosts:
  - 'laptop.nombre-tailnet.ts.net'
```

```powershell
uv run relayforge doctor
uv run relayforge serve
```

En otra terminal, configura Tailscale Serve según la versión local de Tailscale para reenviar HTTPS al backend `http://127.0.0.1:8787`. Comprueba que Funnel esté desactivado. RelayForge valida `Host`, `Origin` y la identidad `Tailscale-User-Login`; no confíes en cabeceras enviadas directamente por clientes.

El CLI desactiva el procesamiento de proxy headers de Uvicorn para conservar la dirección TCP real del proxy local; RelayForge procesa el protocolo reenviado solo desde ese peer confiable. Si aparece `Identidad no permitida.` aun con el login exacto autorizado, comprueba que ejecutas la versión corregida desde su worktree y reinicia el servidor tras actualizar código o configuración. Genera después un código de pairing nuevo; renovar el código por sí solo no corrige un rechazo de identidad.

## Pairing y diagnóstico

Genera el código en la terminal del host y úsalo una vez en el navegador del dispositivo autorizado:

```powershell
uv run relayforge token pair
uv run relayforge doctor --fingerprint > relayforge-fingerprint.json
uv run relayforge doctor --compare .\relayforge-fingerprint.json
```

El código expira a los 10 minutos y solo su hash se guarda en la base de datos. El fingerprint no incluye rutas personales ni tokens. Trátalo como dato operativo del equipo y no lo publiques.

## Inicio automático opcional

La tarea del Programador de tareas se ejecuta con el token interactivo del usuario actual, al iniciar sesión, con nivel limitado. No puede iniciar RelayForge antes del inicio de sesión de Windows. POC-10 no valida aún la disponibilidad de todas las credenciales de agente después de reiniciar; verifica `doctor` antes de depender del servicio.

```powershell
.\scripts\register-task.ps1
Get-ScheduledTask -TaskName RelayForge
.\scripts\register-task.ps1 -Unregister
```

El script no se ejecuta durante el desarrollo ni modifica la configuración de Tailscale, firewall, energía o credenciales. Para retirarlo, usa `-Unregister`.

## Pendiente de validación

Las pruebas automatizadas no sustituyen el pairing desde otro dispositivo Tailscale, la prueba de cabeceras falsificadas desde fuera del host, el reinicio real de la laptop ni la comparación de fingerprints entre PC y laptop. Registra esos resultados antes de declarar completada la fase. La imagen Windows se construye y ejecuta según [Docker en Windows](docker-windows.md); el pairing móvil y el reinicio de la laptop siguen requiriendo comprobación física.
