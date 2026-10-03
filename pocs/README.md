# Arnés de POCs de RelayForge

Este proyecto `uv` es independiente y desechable. Los scripts no forman parte de `src/`. Ejecuta `uv sync --project pocs` desde la raíz para instalar las dependencias. Los resultados se guardan en `pocs/results/<poc>/<fecha>/` y quedan ignorados por Git; todos los archivos de evidencia redactan secretos y rutas de perfil.

## Preparar un repositorio sandbox

```powershell
uv run --project pocs python pocs/setup_sandbox_repo.py --path <directorio>
```

El marcador `.relayforge-sandbox` limita los runners de Git al repositorio generado. `--force` solo reemplaza directorios que contengan ese marcador. Opciones: `--with-submodule`, `--with-lfs` y `--dirty`.

## POCs

| POC | Objetivo y ejecución | Cuota y red | Evidencia |
|---|---|---|---|
| 01 Claude stream-json | `uv run --project pocs python pocs/poc01_claude_stream/run.py --repo <sandbox>`; tres turnos de sesión. `--dry-run` solo imprime argv. La interfaz local se inicia desde `pocs/` con `uv run --project pocs uvicorn poc01_claude_stream.app:app --host 127.0.0.1 --port 8790`. | La ejecución real de Claude puede consumir cuota y red. La interfaz solo escucha en loopback y la llamada real usa cuota/red. | JSONL por turno, stderr, tiempos, resumen de inicialización y `verdict.json`. |
| 02 Codex events | `uv run --project pocs python pocs/poc02_codex_events/run.py --repo <sandbox>`; crea un worktree que se conserva para POC-03. | La ejecución real de Codex puede consumir cuota y red. | Eventos JSONL, histograma, resumen de cambios, `changes.diff`, salida final y `verdict.json`. |
| 03 Antigravity audit | `uv run --project pocs python pocs/poc03_antigravity_audit/run.py --worktree <worktree> --case normal`; los casos disponibles son `normal`, `tamper` y `schema`. `--dry-run` no llama a Antigravity. | La auditoría real de Antigravity puede consumir cuota y red. | Política, hook, hashes antes/después, checks, registro del gate, stream y `verdict.json`. |
| 05 Worktrees | `uv run --project pocs python pocs/poc05_worktree/run.py --repo <sandbox> [--runtime <directorio>]`. No usa agentes. | No consume cuota ni requiere red, salvo descarga configurada de objetos LFS o submódulos. | Pasos, diff y `verdict.json`; el worktree temporal se elimina al terminar. |
| 06 Cancelación | `uv run --project pocs python pocs/poc06_cancel/run.py [--iterations 10]`; sintético, solo Windows. `--real claude|codex|agy --repo <sandbox>` termina el Job Object tras 15 s. | Modo sintético sin cuota/red; `--real` puede consumir cuota y red. | Salidas redirigidas, iteraciones y `verdict.json`. |
| 04 Herramientas MCP | `uv run --project pocs python pocs/poc04_mcp_tools/run.py --repo <sandbox> [--case all|tools|bash_deny|skill_delegation]`; `--dry-run` solo muestra argv. | La ejecución real usa Claude y la API MCP loopback; puede consumir cuota. | `cases.json`, resumen MCP, eventos y `verdict.json`; token y configuración secreta se eliminan al cerrar. | Prueba solo los patrones confirmados en esta versión de Claude; `C3` queda manual si no hay otro MCP anunciado. |
| 07 Reinicio del backend | `uv run --project pocs python pocs/poc07_backend_restart/run.py --repo <sandbox> [--agent claude|codex]`; `--dry-run` muestra argv. | Ejecuta el agente con una petición de análisis larga y puede consumir cuota/red. | Estados reconciliados, streams JSONL y `verdict.json`; Codex usa worktree temporal eliminado al cerrar. | La supervivencia depende del Job Object y de la persistencia de sesión de cada CLI; fallos de entorno quedan como criterios fallidos. |
| 08 Aprobación humana | `uv run --project pocs python pocs/poc08_approval/run.py --repo <sandbox> [--skip-claude]`; `--dry-run` muestra los comandos de Claude. | SQLite local para C1–C7; Claude es opcional con `--skip-claude` y puede consumir cuota. | Base SQLite, archivos de efecto, entradas de permiso, eventos y `verdict.json`. | La prueba MCP usa la función permission prompt observada en esta CLI; sin Claude, C8/C9 quedan manuales. |
| 09 Salud de agentes | `uv run --project pocs python pocs/poc09_health/run.py [--with-auth-simulation]`; `--dry-run` enumera comandos. | Consulta versiones, autenticación y doctor de las CLIs instaladas; puede generar tráfico de proveedor. | `health.json`, `rate_signals.json`, `command_results.json` y `verdict.json`; los directorios de simulación se borran. | La heurística de autenticación es conservadora; agy puede quedar `UNKNOWN` si la ayuda no documenta un comando de auth. |
| 10 Arranque automático | Guía y scripts en `pocs/poc10_autostart/`; `probe.py --dry-run` enumera comandos. | Las pruebas reales consultan versiones, autenticación y, opcionalmente, agentes/Git remoto. | JSON redactado en `%LOCALAPPDATA%\RelayForge-POC\poc10`. | Prueba por separado Logon, StartupS4U y StartupPassword; revisa el registro después de cada reinicio. |
| 11 Tailscale serve | `uv run --project pocs python pocs/poc11_tailscale/app.py`; comprobación local con `local_check.py`. | El servidor escucha solo en loopback. La prueba remota requiere que el usuario configure Tailscale y conecte un móvil. | Log NDJSON y `local_check.json` en el directorio actual. | Demuestra identidad, SSE y que un proceso local puede falsificar las cabeceras; nunca uses Funnel. |

Los runners reales requieren el binario correspondiente en `PATH` o `RELAYFORGE_CLAUDE_BIN`, `RELAYFORGE_CODEX_BIN` o `RELAYFORGE_AGY_BIN`. En Windows, Codex también puede detectarse bajo `%LOCALAPPDATA%`. Si falta el binario, el runner escribe un veredicto `FAIL` y devuelve código 3. Los prompts se pasan por stdin o según la interfaz documentada por cada CLI; no se registran variables de entorno completas.

### POC-10: arranque automático en Windows

Abre PowerShell como el usuario que tiene autenticadas las CLIs. Registra cada modo con su etiqueta para atribuir la evidencia incluso si las tareas corren a la vez:

```powershell
./poc10_autostart/register-task.ps1 -Mode Logon -Deep
./poc10_autostart/register-task.ps1 -Mode StartupS4U -Deep
./poc10_autostart/register-task.ps1 -Mode StartupPassword -Deep
```

Después de reiniciar, cada JSON lleva fecha, modo y PID; no elijas solo el archivo más reciente. StartupS4U y StartupPassword se ejecutan al iniciar Windows; Logon se ejecuta al iniciar sesión. StartupS4U no obtiene los secretos DPAPI de una sesión iniciada.

```powershell
Get-ChildItem "$env:LOCALAPPDATA\RelayForge-POC\poc10" -Filter *.json | Sort-Object LastWriteTime
```

StartupPassword solicita la contraseña mediante `Get-Credential`; el script no la imprime. `register-task.ps1` comprueba que el intérprete exista antes de resolver su ruta.

Al terminar, elimina las tareas:

```powershell
./poc10_autostart/unregister-task.ps1 -Mode StartupPassword
```

`-GitRemote <URL>` consulta ramas con `git ls-remote --heads` (solo lectura). Para probar escritura desde el modo candidato, usa el repositorio privado de pruebas autorizado y la opción `-GitPushRemote`:

```powershell
./poc10_autostart/register-task.ps1 -Mode Logon -GitPushRemote <URL>
```

El `push` crea temporalmente `poc10/<modo>-<fecha>-<pid>` y la elimina al terminar si se creó correctamente. La sonda también borra el repositorio temporal local. Revisa el JSON redactado: `git_push.branch_deleted` debe ser `true`; un fallo de borrado deja la rama de prueba para retirarla manualmente. No uses esta opción con repositorios de trabajo. `probe.py --dry-run --label Logon --git-push-check <URL>` solo enumera los comandos de push y borrado; no ejecuta Git ni escribe evidencia. El `dry-run` del script no contacta el remoto.

### POC-11: Tailscale Serve, identidad y SSE

En una ventana de PowerShell, inicia la app desde `pocs/`:

```powershell
uv run python poc11_tailscale/app.py
```

En otra ventana, desde la misma carpeta, ejecuta `uv run python poc11_tailscale/local_check.py`. El resultado `spoof_accepted_direct: true` es esperado: cualquier proceso local que alcance loopback puede falsificar las cabeceras; no uses esas cabeceras como único control de acceso.

Configura el nombre HTTPS de Tailscale en el móvil y comprueba la sesión SSE durante 10 minutos:

```powershell
tailscale serve --bg 8792
```

Abre `https://<laptop>.<tailnet>.ts.net/` en el móvil, confirma la identidad mostrada y deja abierta la página durante 10 minutos. Al terminar, desactiva Serve:

```powershell
tailscale serve reset
```

**Nunca ejecutes `tailscale funnel`.** La aplicación escucha solo en `127.0.0.1`; la comprobación desde la laptop a la URL tailnet es opcional con `local_check.py --ts-url https://<laptop>.<tailnet>.ts.net`.

La app se ejecuta en primer plano y no se inicia automáticamente al reiniciar. Serve puede conservar la ruta al puerto local; si la app no está escuchando, el sitio devuelve HTTP 502. Vuelve a iniciar `app.py` después del reinicio.

## Pruebas locales

Desde `pocs/`: `uv run python -m pytest -q`. Ninguna prueba invoca un agente real. `JobObject` y la prueba de árboles de procesos requieren Windows; en otros sistemas la prueba se omite.
