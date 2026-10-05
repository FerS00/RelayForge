# Docker en Windows

RelayForge está en desarrollo temprano y usa Windows Job Objects. Requiere Server Core 2019, Hyper-V y Windows containers. Esta imagen no porta el runtime a Linux; aceptación real completa pendiente, véase [testing](testing.md).

## Requisitos y estado verificado

- Windows 10 Pro con virtualización Hyper-V activa y las características `Microsoft-Hyper-V-All` y `Containers` habilitadas.
- Docker Desktop instalado en modo all-users y comandos ejecutados explícitamente en el contexto `desktop-windows`.
- Red NAT de Compose `172.30.240.0/24`; RelayForge usa la IP fija `172.30.240.10` y confía únicamente en el gateway `172.30.240.1` como proxy.
- Windows NAT rechaza publicar puertos con una IP de host (`Windows does not support host IP addresses in NAT settings`), así que Compose no declara `ports`. El servicio conserva la IP fija `172.30.240.10`. Tailscale Serve admite el backend `http://127.0.0.1`; una regla persistente de Windows `portproxy` enlaza solo `127.0.0.1:8792` con `172.30.240.10:8792`, sin exponer el puerto en la LAN.
- La imagen nueva instala Claude Code, Codex y Antigravity. Perfiles se crean por login en el runtime y quedan fuera de la imagen; no se copia auth del host.

Observado durante 2026-10-05: Engine Windows 29.8.1, contenedor antiguo healthy y cuatro volúmenes; imagen nueva con Claude 2.1.288, Codex 0.159.2 y Antigravity 1.2.16 construida pero sin recreación final. Compose declara cinco volúmenes. Durante la revisión documental el contexto predeterminado es Linux, pero la consulta explícita a `desktop-windows` confirma Engine Windows 29.8.1, imagen nueva conservada y contenedor antiguo healthy. Usar el contexto Windows explícito evita consultar el Engine equivocado. El pairing de una versión anterior no acredita consola nueva desde móvil. Login Codex/Antigravity y tarea real siguen pendientes.

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

Las dos allowlists del archivo `.env.docker` usan arreglos JSON. El archivo está excluido de Git y del contexto de build; contiene solo identidad y hostname permitidos, no tokens. No publiques puertos de host ni amplíes la allowlist del proxy NAT. La regla loopback se configura una vez en PowerShell elevado:

El dominio HTTPS tailnet-only no cambia. Configura el puente local y el backend de Serve así:

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

Usa el código una vez desde el dispositivo permitido. El servicio requiere que Claude Code esté instalado y que exista el workspace configurado.

## Diagnóstico y persistencia

```powershell
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml logs --tail 100 relayforge
docker --context desktop-windows inspect --format '{{.State.Health.Status}}' relayforge
docker --context desktop-windows volume ls --filter name=relayforge
netsh interface portproxy show v4tov4
```

`docker --context desktop-windows compose stop` y `docker --context desktop-windows compose down` conservan los volúmenes. No uses `down -v` si necesitas la base de datos, el workspace, los proyectos o la sesión de Claude.

Los Engines Windows y Linux mantienen imágenes y volúmenes distintos. El respaldo en `%LOCALAPPDATA%\DockerTransitionBackup\20261004-210309` y la parada de `agent-ops` pertenecen a la transición histórica. En la revisión actual, `agent-ops` aparece healthy en Linux y RelayForge se consulta explícitamente en `desktop-windows`; el contexto predeterminado es Linux. No borrar volúmenes ni cambiar el contexto global de otros proyectos al operar RelayForge.
