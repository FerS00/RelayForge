# Guía — cerrar las reservas R-1, R-2 y R-4a en la laptop

Sesión única de unos 40 minutos con **un solo reinicio**. Resuelve:

- **R-1:** `git push` desde una tarea programada, con Git Credential Manager, en los tres modos de arranque.
- **R-2:** discrepancia de horarios del arranque (se contrasta con los registros de eventos de Windows).
- **R-4a:** falsificación de cabeceras de Tailscale desde otro dispositivo.

R-4b (que la app arranque sola tras reiniciar) se cierra en la Fase 4 con el servicio real de RelayForge.

Marcadores: `<repo-de-prueba>` es la URL HTTPS del repositorio privado vacío creado para R-1 (te la doy en el chat); `<laptop>.<tailnet>` es el nombre MagicDNS de la laptop (`tailscale status`); `<pc>` es el nombre de la PC principal en Tailscale.

---

## Paso 0 — Traer el código (laptop, PowerShell normal)

```powershell
cd C:\Dev\RelayForge
git pull --ff-only
cd pocs
uv sync
uv run python -m pytest -q
uv run python poc10_autostart/probe.py --dry-run --label Logon --git-push-check <repo-de-prueba>
```

El `--dry-run` debe listar un `git push` a una rama `poc10/...` y su borrado. Ninguna línea debe contener `--force`.

## Paso 1 — R-2: registros de eventos (PowerShell **como administrador**)

Activa el registro operativo del Programador de tareas. Viene desactivado por defecto y es la pieza que faltó para reconciliar los tiempos:

```powershell
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true
```

Primero, intenta reconciliar la ronda anterior (arranque del 2026-10-03 hacia las 10:08) con lo que todavía conserve Windows:

```powershell
$desde = Get-Date '2026-10-03 10:00'; $hasta = Get-Date '2026-10-03 10:20'
Get-WinEvent -FilterHashtable @{LogName='System'; Id=12,6005,6006,1074; StartTime=$desde; EndTime=$hasta} -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id,ProviderName | Sort-Object TimeCreated | Format-Table -AutoSize
Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4624; StartTime=$desde; EndTime=$hasta} -ErrorAction SilentlyContinue | Where-Object { $_.Properties[8].Value -in 2,11 } | Select-Object TimeCreated,@{n='LogonType';e={$_.Properties[8].Value}} | Format-Table -AutoSize
```

- `Id 12` / `6005`: arranque del sistema. `1074`: reinicio solicitado.
- `4624` con `LogonType` 2 o 11: inicio de sesión interactivo (contraseña, PIN o huella). **No copies otros campos**: el evento incluye tu nombre de usuario y el de la máquina.

Guarda la salida para el paso 5.

## Paso 2 — R-1: registrar las tres tareas con push (PowerShell como administrador)

```powershell
cd C:\Dev\RelayForge\pocs
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\unregister-task.ps1 -All
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\register-task.ps1 -Mode Logon -Deep -GitPushRemote <repo-de-prueba>
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\register-task.ps1 -Mode StartupS4U -Deep -GitPushRemote <repo-de-prueba>
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\register-task.ps1 -Mode StartupPassword -Deep -GitPushRemote <repo-de-prueba>
```

La última pide tu contraseña en una ventana de Windows; el script no la guarda.

## Paso 3 — Reiniciar y anotar las horas

1. Mira la hora y **anótala**. Reinicia.
2. Cuando aparezca la pantalla de bloqueo, **anota la hora** y espera 3 minutos **sin iniciar sesión**.
3. Inicia sesión y **anota la hora exacta**.
4. Espera otros 3 minutos.

Las tres horas anotadas son la referencia para R-2.

## Paso 4 — Recoger evidencia (PowerShell como administrador)

```powershell
cd C:\Dev\RelayForge\pocs
Get-ScheduledTaskInfo -TaskName 'RelayForge-POC10-*' | Select-Object TaskName,LastRunTime,LastTaskResult | Format-Table -AutoSize

$desde = (Get-Date).AddMinutes(-20)
Get-WinEvent -FilterHashtable @{LogName='System'; Id=12,6005; StartTime=$desde} -ErrorAction SilentlyContinue | Select-Object TimeCreated,Id | Sort-Object TimeCreated | Format-Table -AutoSize
Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4624; StartTime=$desde} -ErrorAction SilentlyContinue | Where-Object { $_.Properties[8].Value -in 2,11 } | Select-Object TimeCreated,@{n='LogonType';e={$_.Properties[8].Value}} | Format-Table -AutoSize
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational'; Id=100,102,107,118,119; StartTime=$desde} -ErrorAction SilentlyContinue | Where-Object { $_.Message -like '*RelayForge-POC10*' } | Select-Object TimeCreated,Id,@{n='Tarea';e={($_.Message -split '"')[1]}} | Sort-Object TimeCreated | Format-Table -AutoSize
```

Significado de los IDs del Programador de tareas: 107 = disparo por tiempo o arranque, 118 = disparo por arranque del sistema, 119 = disparo por inicio de sesión, 100 = tarea iniciada, 102 = tarea terminada.

Envía los JSON nuevos a la PC por Taildrop:

```powershell
Get-ChildItem $env:LOCALAPPDATA\RelayForge-POC\poc10\*.json | Sort-Object LastWriteTime | Select-Object -Last 3 | ForEach-Object { tailscale file cp $_.FullName <pc>: }
```

Limpia las tareas:

```powershell
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\unregister-task.ps1 -All
Get-ScheduledTask -TaskName 'RelayForge-POC10-*' -ErrorAction SilentlyContinue
```

La última línea no debe mostrar nada.

## Paso 5 — R-4a: falsificación desde otro dispositivo (laptop + PC)

En la laptop, **ventana 1** (PowerShell normal):

```powershell
cd C:\Dev\RelayForge\pocs
uv run python poc11_tailscale/app.py
```

**Ventana 2**:

```powershell
tailscale serve --bg 8792
tailscale serve status
```

Avisa en el chat: «serve activo». Desde la PC principal enviaré a `https://<laptop>.<tailnet>.ts.net/whoami` una petición con la cabecera falsa `Tailscale-User-Login: attacker@example.com`. Lo esperado es que Tailscale la descarte y la app vea tu identidad real (o ninguna), nunca `attacker@example.com`.

Cuando confirme el resultado, en la ventana 2:

```powershell
tailscale serve reset
tailscale serve status
```

Debe decir `No serve config`. Cierra la ventana 1 con `Ctrl+C`.

## Qué enviarme

1. «Enviado» (los 3 JSON por Taildrop).
2. Las tres horas anotadas del paso 3.
3. La salida de las consultas de eventos de los pasos 1 y 4 (solo las columnas indicadas).
4. La salida de `Get-ScheduledTaskInfo` del paso 4.

Opcional al terminar todo: `wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:false` para volver a desactivar el registro del Programador de tareas.
