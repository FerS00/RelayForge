# Docker en Windows

RelayForge está en desarrollo temprano y usa Windows Job Objects. Requiere Server Core 2019, Hyper-V y Windows containers. Esta imagen no porta el runtime a Linux; aceptación real completa pendiente, véase [testing](testing.md).

## Requisitos y estado verificado

- Windows 10 Pro con virtualización Hyper-V activa y las características `Microsoft-Hyper-V-All` y `Containers` habilitadas.
- Docker Desktop instalado en modo all-users y comandos ejecutados explícitamente en el contexto `desktop-windows`.
- Red NAT de Compose `172.30.240.0/24`; RelayForge usa la IP fija `172.30.240.10` y confía únicamente en el gateway `172.30.240.1` como proxy.
- Windows NAT rechaza publicar puertos con una IP de host (`Windows does not support host IP addresses in NAT settings`), así que Compose no declara `ports`. El servicio conserva la IP fija `172.30.240.10`. Tailscale Serve admite el backend `http://127.0.0.1`; una regla persistente de Windows `portproxy` enlaza solo `127.0.0.1:8792` con `172.30.240.10:8792`, sin exponer el puerto en la LAN.
- La imagen nueva instala Claude Code, Codex y Antigravity. Perfiles se crean por login en el runtime y quedan fuera de la imagen; no se copia auth del host.

Estado comprobado el 2026-10-05 con el contexto explícito `desktop-windows`: Engine 29.8.2; la imagen `relayforge:windows` tiene ID `sha256:ac851022dd92068453a314bb9b00f1ee2b0a621d788371f871ebb7988cc5c4a5` y el contenedor `relayforge` está `healthy`. Hay cinco volúmenes persistentes: `relayforge_relayforge-home`, `-workspace`, `-projects`, `-claude` y `-codex`. Se comprobaron HTTP 200 local y HTTPS tailnet desde la misma laptop; esto no demuestra acceso desde otro dispositivo. Claude Code 2.1.288, Codex 0.159.2 y Antigravity 1.2.16 ejecutan como `ContainerUser`. Tras la recreación con el selector nuevo, Codex conserva auth disponible y siete modelos anunciados en su caché. Claude devuelve `loggedIn=false`; Antigravity solicita iniciar sesión y no entrega modelos. El montaje de perfiles no basta para acreditar persistencia efectiva de auth; recuperar ambos logins sigue pendiente, y AGY es necesario para el Job de esta tarea. El probe de Codex aún puede imprimir una advertencia no fatal al limpiar directorios temporales.

La imagen fija ACL del ejecutable Antigravity: quita herencia, da control total a administrador/SYSTEM y solo lectura/ejecución a `ContainerUser`. La ACL se comprobó dentro del contenedor y una apertura de escritura como `ContainerUser` fue denegada. La base SQLite reportó la migración `0008_agent_dispatch`; la recreación actual conservó exactamente un proyecto, dos Jobs, cuatro steps, 26 eventos y una aprobación: conteos y hashes de todas las filas de esas tablas coinciden antes/después. Playwright abrió la UI por HTTPS tailnet con viewport 390×844 y el pairing rechazó un código inválido con HTTP 403 y el mensaje esperado. Esta es una prueba en el navegador de la laptop, no en teléfono físico; el propietario creó/aprobó JOB-000002 manualmente en el teléfono y cerró el navegador durante implementación; el Job continuó y completó la implementación, pero falló en el check antes de auditoría. El check corregido pasó después de recrear; el pipeline completo sigue pendiente.

## Configuración y arranque

Desde la raíz del repositorio, crea el archivo local y reemplaza los valores de ejemplo con el login Tailscale y el hostname HTTPS exactos:

```powershell
Copy-Item docker.env.example .env.docker
notepad .env.docker
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml config --quiet
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml build
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml up -d
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml ps
```

Las dos allowlists del archivo `.env.docker` usan arreglos JSON. El archivo está excluido de Git y del contexto de build; contiene solo identidad y hostname permitidos, no tokens. No publiques puertos de host ni amplíes la allowlist del proxy NAT. La regla loopback se configura una vez en PowerShell elevado. Como el dominio HTTPS tailnet-only no cambia, configura el puente local y el backend de Serve con:

```powershell
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8792 connectaddress=172.30.240.10 connectport=8792
netsh interface portproxy show v4tov4
tailscale serve --bg http://127.0.0.1:8792
tailscale serve status
```

Inicia Claude Code dentro del volumen persistente y completa el login interactivo:

```powershell
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml exec relayforge cmd.exe /c claude
```

La imagen instala las CLI de Codex `0.159.2` y Antigravity `1.2.16`. Sus credenciales no se copian desde Windows: Codex usa el volumen `relayforge-codex`; Antigravity guarda su perfil bajo `C:\relayforge-claude`, junto a los datos persistentes de Claude. Completa cada inicio de sesión una vez desde la laptop:

```powershell
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml exec relayforge codex login --device-auth
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml exec -it relayforge agy
```

Para Codex, abre el enlace del comando y completa autorización; para Antigravity sigue el flujo CLI. No publiques códigos/tokens. Confirma Codex con `codex login status` y Antigravity con una sesión autenticada. Volúmenes preservan archivos; un login dependiente de credenciales del OS debe probarse tras recreación. No uses `docker --context desktop-windows compose down -v`.

Para crear un código de pairing:

```powershell
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml exec relayforge relayforge.exe token pair
```

Usa el código una vez desde el dispositivo permitido. El servicio requiere que Claude Code esté instalado y que exista el workspace configurado. No registres ni compartas el código.

## Diagnóstico y persistencia

```powershell
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml logs --tail 100 relayforge
docker --context desktop-windows inspect --format '{{.State.Health.Status}}' relayforge
docker --context desktop-windows volume ls --filter name=relayforge
netsh interface portproxy show v4tov4
```

`docker --context desktop-windows compose stop` y `docker --context desktop-windows compose down` conservan los volúmenes. No uses `down -v` si necesitas la base de datos, el workspace, los proyectos o la sesión de Claude.

Los Engines Windows y Linux mantienen imágenes y volúmenes distintos. El respaldo en `%LOCALAPPDATA%\DockerTransitionBackup\20261004-210309` y la parada de `agent-ops` pertenecen a la transición histórica. En la revisión actual, `agent-ops` aparece healthy en Linux y RelayForge se consulta explícitamente en `desktop-windows`; el contexto predeterminado es Linux. No borrar volúmenes ni cambiar el contexto global de otros proyectos al operar RelayForge.

La imagen actual incluye el selector de modelos y la conservación de USERPROFILE para los checks Git. Antigravity aprobó el código y nueve checks en la auditoría `a1d9a329ddfc4c36a7aa417b98cbe988`; esta aprobación no sustituye la auditoría del Job real. No se ampliaron safe.directory ni permisos y se preservaron los cinco volúmenes.

## Capacidades del contenedor tras CH-06/07

En `container_mode` el explorador de entregables y la descarga ZIP funcionan sobre los volúmenes montados; los previews (`preview_unavailable`) y el escritorio GUI (`desktop_enabled` forzado a falso) no están disponibles. Esfuerzo y herramientas por conversación funcionan igual que en nativo. Docker Desktop ejecuta a la vez el motor Linux (`desktop-linux`) y el Windows (`desktop-windows`); dirige siempre los comandos de RelayForge con `docker --context desktop-windows …` sin cambiar el contexto global.

Reconstrucción 2026-10-09: imagen anterior etiquetada `relayforge:windows-pre-ch05` (`ac851022…`); copia SQLite en caliente `C:\relayforge-home\relayforge-pre-ch05.db` dentro del volumen (con Hyper-V en marcha `docker cp` no está soportado); `compose build` → imagen `4b526a42…`; `compose up -d` recreó el contenedor con los cinco volúmenes, estado healthy, migración 0008 → 0014 con los mismos conteos (4 conversaciones, 2 mensajes, 3 Jobs, 45 eventos) y `foreign_key_check` vacío. Rollback: `docker --context desktop-windows tag relayforge:windows-pre-ch05 relayforge:windows`, restaurar `relayforge-pre-ch05.db` como `relayforge.db` con el contenedor detenido y `compose up -d`.

Actualización 2026-10-10: imagen `c7fd92a2…` (CH-04/06/07, correcciones del chat y `relayforge backup/restore` de la Fase 14), contenedor healthy, migración 0014 y conteos 4/2/3/45 conservados. Rollback: `relayforge:windows-pre-f14` (`cc0c73ad…`) o `relayforge:windows-pre-ch05b` (`4b526a42…`) más las copias `relayforge-pre-f14.db`/`relayforge-pre-ch05b.db` del volumen. Dentro del contenedor, `relayforge backup --output C:\relayforge-home\backups` crea una copia consistente sin detener el servicio.
