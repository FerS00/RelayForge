> Material histórico de POCs/validaciones previas. Contrasta procedimientos y resultados con el [plan vigente](PLAN_PROYECTO.md) y las guías actuales de instalación/Docker. No acredita aceptación del despliegue nuevo.

# Guía paso a paso — Fase 0C en la laptop (POC-10 y POC-11)

- Laptop: `<laptop>` (IP de Tailscale `100.x.y.z`) · URL tailnet: `https://<laptop>.<tailnet>.ts.net/`
- PC principal: `<pc>` · Celular: `<celular>` (consulta los nombres e IPs con `tailscale status`)
- Tiempo estimado: unos 45 minutos (3 reinicios).
- Ninguna prueba sube nada a Internet. La evidencia queda en la laptop y no contiene datos personales (se redacta).

### Estado comprobado el 2026-10-03

- Tras el reinicio, los tres modos de POC-10 ejecutaron las sondas profundas: Claude, Codex y agy quedaron `AVAILABLE`; los tres turnos de prueba terminaron con código 0. Se verificaron por separado `Logon` (sesión 1), `StartupS4U` (sesión 0) y `StartupPassword` (sesión 0).
- La ejecución automática simultánea generó solo dos JSON para tres tareas porque el nombre anterior usaba precisión de un segundo. El script ahora añade etiqueta y PID y crea archivos en modo exclusivo; vuelve a registrar las tareas para que incorporen la etiqueta antes de otra prueba automática.
- `git ls-remote --heads` al remoto público respondió correctamente, pero eso no prueba credenciales GCM: el repositorio admite consultas anónimas. No se hizo `push`; no hay remoto de pruebas configurado en esta laptop.
- En el celular se confirmó `/whoami` y el SSE se mantuvo 600 segundos (observación del usuario). El ataque local de cabeceras fue aceptado, como espera esta POC; las cabeceras Tailscale no deben usarse como único control de acceso.
- Tras el reinicio, `tailscale serve status` conserva la ruta al puerto 8792, pero la app no estaba escuchando y `/whoami` devolvió HTTP 502. `app.py` debe iniciarse manualmente; no tiene arranque automático.

---

## Paso 0 — Preparación (una sola vez)

Abre **PowerShell normal** (no como administrador) en la laptop:

```powershell
cd C:\Dev
git clone https://github.com/FerS00/RelayForge.git
cd C:\Dev\RelayForge\pocs
uv sync
uv run python -m pytest -q
```

Resultado esperado: `36 passed`. Si `uv` no existe, instálalo igual que en la PC; si `C:\Dev` no existe, créalo antes con `mkdir C:\Dev`.

Ahora la **línea base** (sesión iniciada, interactiva):

```powershell
uv run python poc10_autostart/probe.py --deep
```

Resultado esperado: una línea `POC-10: claude=AVAILABLE, codex=AVAILABLE, agy=AVAILABLE; evidencia=<fecha>-manual-<pid>.json`. Si alguno no sale `AVAILABLE`, detente y avísame: hay que arreglar la autenticación antes de seguir.

> Si PowerShell bloquea los scripts `.ps1` (error de "execution policy"), usa la forma `powershell -ExecutionPolicy Bypass -File …` que se indica en cada paso. Solo afecta a esa ejecución; no cambia la política del sistema.

---

## POC-10 — Arranque automático (3 modos, un reinicio por modo)

Para cada modo se registra una tarea programada que ejecuta la sonda sola tras reiniciar. Así sabremos con qué modo RelayForge podrá arrancar sin que tengas que hacer nada.

### Modo 1: `Logon` (al iniciar sesión)

En **PowerShell normal**, dentro de `C:\Dev\RelayForge\pocs`:

```powershell
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\register-task.ps1 -Mode Logon -Deep
```

1. Reinicia la laptop.
2. Inicia sesión normalmente y **espera 3 minutos** sin hacer nada especial.
3. Abre PowerShell y revisa el último resultado:

```powershell
Get-ScheduledTaskInfo -TaskName RelayForge-POC10-Logon | Select-Object LastRunTime,LastTaskResult
Get-ChildItem $env:LOCALAPPDATA\RelayForge-POC\poc10 | Sort-Object LastWriteTime | Select-Object -Last 1 | Get-Content -Raw
```

4. Anota o copia la salida (ver «Cómo enviarme los resultados» al final).
5. Elimina la tarea:

```powershell
cd C:\Dev\RelayForge\pocs
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\unregister-task.ps1 -Mode Logon
```

### Modo 2: `StartupS4U` (al encender, **sin** iniciar sesión, sin contraseña)

Abre **PowerShell como administrador** (clic derecho → Ejecutar como administrador):

```powershell
cd C:\Dev\RelayForge\pocs
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\register-task.ps1 -Mode StartupS4U -Deep
```

1. Reinicia la laptop.
2. **No inicies sesión**: deja la pantalla de bloqueo **3 minutos**. Esto es justo lo que se prueba: si los agentes funcionan sin sesión iniciada.
3. Inicia sesión y revisa el resultado (igual que en el modo 1, cambiando el nombre de la tarea):

```powershell
Get-ScheduledTaskInfo -TaskName RelayForge-POC10-StartupS4U | Select-Object LastRunTime,LastTaskResult
Get-ChildItem $env:LOCALAPPDATA\RelayForge-POC\poc10 | Sort-Object LastWriteTime | Select-Object -Last 1 | Get-Content -Raw
```

4. Elimina la tarea (PowerShell como administrador):

```powershell
cd C:\Dev\RelayForge\pocs
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\unregister-task.ps1 -Mode StartupS4U
```

Es probable que en este modo algún agente salga `AUTH_REQUIRED` o falle: S4U no tiene acceso a los secretos protegidos de tu sesión. Ese resultado también sirve.

### Modo 3: `StartupPassword` (al encender, sin iniciar sesión, con tu contraseña)

En **PowerShell como administrador**:

```powershell
cd C:\Dev\RelayForge\pocs
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\register-task.ps1 -Mode StartupPassword -Deep
```

Se abrirá una ventana de Windows pidiendo tu contraseña. **La escribes tú**; el script no la guarda ni la muestra, solo se la entrega al Programador de tareas.

1. Reinicia la laptop.
2. **No inicies sesión**: espera 3 minutos en la pantalla de bloqueo.
3. Inicia sesión y revisa:

```powershell
Get-ScheduledTaskInfo -TaskName RelayForge-POC10-StartupPassword | Select-Object LastRunTime,LastTaskResult
Get-ChildItem $env:LOCALAPPDATA\RelayForge-POC\poc10 | Sort-Object LastWriteTime | Select-Object -Last 1 | Get-Content -Raw
```

4. Limpieza final de todas las tareas de la prueba (PowerShell como administrador):

```powershell
cd C:\Dev\RelayForge\pocs
powershell -ExecutionPolicy Bypass -File .\poc10_autostart\unregister-task.ps1 -All
```

Comprueba que no quedó ninguna: `Get-ScheduledTask -TaskName 'RelayForge-POC10-*' -ErrorAction SilentlyContinue` no debe mostrar nada.

---

## POC-11 — Tailscale serve, identidad y streaming desde el celular

### 1. Arrancar la app de prueba (ventana 1, PowerShell normal)

```powershell
cd C:\Dev\RelayForge\pocs
uv run python poc11_tailscale/app.py
```

Déjala abierta. Escucha **solo** en `127.0.0.1:8792`.

### 2. Comprobación local (ventana 2, PowerShell normal)

```powershell
cd C:\Dev\RelayForge\pocs
uv run python poc11_tailscale/local_check.py
```

Esperado: `"spoof_accepted_direct": true`. Confirma en la laptop lo que ya vimos en la PC: un proceso local puede falsificar la identidad, así que RelayForge usará además el emparejamiento con cookie.

### 3. Publicar en tu tailnet (ventana 2)

```powershell
tailscale serve --bg 8792
tailscale serve status
```

Si Tailscale pide habilitar los certificados HTTPS de la tailnet, mostrará un enlace a la consola de administración: ábrelo y actívalo (solo hace falta una vez). Debe quedar `https://<laptop>.<tailnet>.ts.net` apuntando a `127.0.0.1:8792`.

**Nunca uses `tailscale funnel`**: eso lo expondría a Internet.

### 4. Probar desde el celular

1. Con Tailscale activo en el celular, abre `https://<laptop>.<tailnet>.ts.net/`.
2. Anota qué muestra en `Tailscale-User-Login` (debería ser tu cuenta de Tailscale).
3. Deja la página abierta **10 minutos** con la pantalla encendida: el contador debe avanzar uno por segundo (cerca de 600).
4. Bloquea el celular 1 minuto y vuelve: debe reconectarse solo y seguir contando sin volver a 0 (el contador de reconexiones sube).

Avísame cuando el paso 3 esté activo: también puedo abrir la URL desde la PC principal y verificar la identidad que llega desde otro equipo.

### 5. Comprobación desde la propia laptop (ventana 2)

```powershell
uv run python poc11_tailscale/local_check.py --ts-url https://<laptop>.<tailnet>.ts.net
```

### 6. Apagar todo

```powershell
tailscale serve reset
tailscale serve status
```

`status` debe decir `No serve config`. Después cierra la ventana 1 con `Ctrl+C`.

---

## Cómo enviarme los resultados

Cualquiera de estas dos opciones:

- **Pegar en el chat:** la salida de cada `Get-Content -Raw` de la POC-10 (3 JSON), la salida de los dos `local_check.py` y lo que viste en el celular (identidad, contador final y si se reconectó).
- **Taildrop** (envío directo por Tailscale a la PC principal), desde `C:\Dev\RelayForge\pocs`:

```powershell
Get-ChildItem $env:LOCALAPPDATA\RelayForge-POC\poc10\*.json | ForEach-Object { tailscale file cp $_.FullName <pc>: }
tailscale file cp .\poc11_tailscale.ndjson <pc>:
```

En ese caso dime «enviado» y los recojo en la PC.

Los JSON no contienen tu correo ni secretos (la sonda los redacta). Aun así, si ves algo que no quieras compartir, bórralo antes de enviarlo.
