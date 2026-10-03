# ESPECIFICACIÓN TÉCNICA (PARA CODEX) — Fase 0C: POC-10 (arranque automático) y POC-11 (Tailscale serve)

- Plan: `docs/PLAN_PROYECTO.md`, Fase 0 (aprobada), secciones 26 (T9, T10), 31, 32 y 38 (POC-10 y POC-11).
- Ejecución: **en la laptop** (Windows 10 Pro), por el usuario o por el coordinador cuando tenga acceso. Codex escribe los scripts; no ejecuta nada que registre tareas ni cambie la configuración de Tailscale.
- Dependencia: el arnés de `pocs/` (Fases 0A y 0B).

## OBJETIVO

POC-10: determinar con qué modo de arranque automático de Windows (tarea programada) las tres CLIs de agentes y Git pueden autenticarse sin interacción tras reiniciar la laptop.
POC-11: verificar que `tailscale serve` hacia `127.0.0.1` entrega cabeceras de identidad (`Tailscale-User-Login`, etc.), que un stream SSE se mantiene estable durante 10 minutos desde el móvil y **medir el riesgo de falsificación de cabeceras desde procesos locales**.

## ARCHIVOS AFECTADOS

Crear:
```
pocs/poc10_autostart/probe.py
pocs/poc10_autostart/register-task.ps1
pocs/poc10_autostart/unregister-task.ps1
pocs/poc11_tailscale/app.py
pocs/poc11_tailscale/local_check.py
pocs/tests/test_probe_parse.py
pocs/tests/test_tailscale_app.py
```
Modificar: `pocs/README.md` (secciones POC-10 y POC-11, con la guía paso a paso para el usuario) y `pocs/tests/test_dry_run.py` (añadir `probe.py --dry-run`).

## MODELOS Y FIRMAS

### `poc10_autostart/probe.py`
CLI: `probe.py [--out-dir D] [--deep] [--git-remote-check URL] [--dry-run]`.
- `--out-dir` por defecto: `%LOCALAPPDATA%\RelayForge-POC\poc10` (creado si falta).
- Registra en `<out-dir>/<YYYYmmdd-HHMMSS>.json` (redactado con `common.redact`):
  - Contexto: `whoami` (`getpass.getuser()`), si existe el perfil (`USERPROFILE`), el ID de sesión de Windows (`ProcessIdToSessionId` vía `ctypes`; la sesión 0 indica un servicio sin escritorio), `os.environ` **solo** con las claves `USERNAME`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA` y `PATH` (longitud y si contiene las rutas de los binarios, no el valor completo), y el tiempo desde el arranque del sistema (`psutil.boot_time()`).
  - Por agente: `locate` + `--version` + autenticación (`claude auth status`, `codex login status`; agy: `UNKNOWN` salvo con `--deep`).
  - `--deep` (consume cuota mínima): Claude `-p --output-format stream-json --verbose` con el prompt «Responde solo OK» (evento `type=result`, `is_error`); Codex `exec --json --skip-git-repo-check -s read-only -C <out-dir> -` con el prompt «Responde solo OK» (`turn.completed`); agy `-p "Responde solo OK. No ejecutes comandos." --output-format stream-json --print-timeout 60s` (`event=result`, `status`, `response`). Timeout de 120 s por agente; siempre con `JobObject`.
  - `--git-remote-check URL`: `git ls-remote --heads URL` con `GIT_TERMINAL_PROMPT=0` y `GCM_INTERACTIVE=never` → registra el código de salida y si hubo error de credenciales (sin la salida completa). **Solo lectura; no hace push.**
- Al final imprime una línea de resumen y sale con 0 aunque haya fallos (es una sonda).
- `--dry-run`: imprime los comandos que ejecutaría.

### `poc10_autostart/register-task.ps1`
Parámetros: `-Mode Logon|StartupS4U|StartupPassword`, `-Deep` (switch), `-GitRemote <url>` (opcional).
- Nombre de la tarea: `RelayForge-POC10-<Mode>`. Acción: el `python.exe` del venv de `pocs` (ruta resuelta desde `$PSScriptRoot\..\.venv\Scripts\python.exe`) con `-X utf8 <probe.py> [--deep] [--git-remote-check URL]`. Directorio de trabajo: `$PSScriptRoot\..`.
- `Logon`: disparador `AtLogOn` para el usuario actual, `LogonType Interactive`.
- `StartupS4U`: disparador `AtStartup`, principal con el usuario actual y `LogonType S4U` (sin contraseña; sin acceso a los secretos protegidos con DPAPI de la sesión).
- `StartupPassword`: disparador `AtStartup`, `LogonType Password`; la contraseña **la introduce el usuario** con `Get-Credential` dentro del script (el script nunca la guarda ni la imprime). Requiere ejecutar PowerShell como el mismo usuario.
- Configuración común: `-ExecutionTimeLimit (New-TimeSpan -Minutes 10)`, sin repetición, `-StartWhenAvailable`.
- No eleva privilegios por su cuenta: si el modo requiere administrador y no lo es, muestra un mensaje y sale.
- `unregister-task.ps1 [-Mode …|-All]` elimina las tareas `RelayForge-POC10-*`.

### `poc11_tailscale/app.py`
FastAPI en `127.0.0.1:8792` (`python app.py [--port 8792] [--log F]`). `create_app(log_path: Path) -> FastAPI`.
- `GET /` → HTML mínimo (sin recursos externos) que muestra `/whoami` y abre un `EventSource('/sse')`, con contador, reconexiones y última marca de tiempo.
- `GET /whoami` → JSON con las cabeceras `Tailscale-User-Login`, `Tailscale-User-Name`, `Tailscale-User-Profile-Pic` (solo indica si existe), `Host`, `Origin`, `X-Forwarded-For`, `X-Forwarded-Proto` y `request.client.host`.
- `GET /sse` → `text/event-stream`; un evento `tick` por segundo con `id: <n>` y `data: {"n":…,"ts":…}`, más un comentario `: ping` cada 15 s. Respeta `Last-Event-ID` (continúa desde n+1). Duración máxima configurable (`--sse-minutes`, por defecto 15).
- Cada petición se registra en el log NDJSON: ruta, las cabeceras de identidad anteriores, `client.host` y `ts`. Solo esas cabeceras (sin cookies ni `Authorization`).

### `poc11_tailscale/local_check.py`
`local_check.py [--port 8792] [--ts-url https://<host>.<tailnet>.ts.net]`:
1. `GET http://127.0.0.1:<port>/whoami` sin cabeceras → `identity_absent_direct`.
2. Ídem con la cabecera falsificada `Tailscale-User-Login: attacker@example.com` → `spoof_accepted_direct` (esperado: **true**; demuestra que cualquier proceso local puede falsificar la identidad si la app confía solo en las cabeceras).
3. Si se pasa `--ts-url`: `GET <ts-url>/whoami` desde la propia laptop → registra la identidad que añade Tailscale.
4. Guarda `local_check.json` y lo imprime.

## REGLAS DE NEGOCIO Y CASOS LÍMITE

1. Ningún script ejecuta `tailscale serve`, `tailscale funnel` ni registra tareas por su cuenta durante las pruebas; eso lo hace el usuario siguiendo el README.
2. El README incluye: la secuencia `tailscale serve --bg 8792` → abrir `https://<laptop>.<tailnet>.ts.net/` en el móvil durante 10 min → `tailscale serve reset` al terminar. La advertencia: **nunca** `tailscale funnel`.
3. Las pruebas unitarias no requieren Tailscale ni tareas programadas: `test_tailscale_app` (whoami refleja las cabeceras; SSE emite ticks con ids y respeta `Last-Event-ID` con una duración de prueba corta) y `test_probe_parse` (heurística de autenticación, extracción del resultado de cada agente a partir de líneas de ejemplo).
4. Sin `shell=True`, sin flags prohibidos, sin rutas personales literales, UTF-8 sin BOM (los `.ps1` en UTF-8 **con** BOM para PowerShell 5.1, con finales de línea CRLF).

## CRITERIOS DE ACEPTACIÓN

1. Solo se crean o modifican los archivos listados.
2. Ruff y pytest de `pocs/` pasan.
3. `probe.py --dry-run` sale con código 0.
4. El README contiene la guía para el usuario de POC-10 (los tres modos, con reinicio entre pruebas) y de POC-11.
5. Los `.ps1` pasan una comprobación de sintaxis: `powershell -NoProfile -Command "[System.Management.Automation.Language.Parser]::ParseFile('<archivo>',[ref]$null,[ref]$e) | Out-Null; $e.Count"` → 0 (la ejecuta el coordinador si el sandbox lo impide).
