# Windows nativo: staging CH-01

Para arranque manual, backups y recuperación, consulta [Operación y recuperación](operations.md).

Backend en la sesión del usuario Windows, listener 127.0.0.1 y puerto separado de Docker. No instala autorun, cambia Tailscale ni copia credenciales. Usa la autenticación existente de Codex CLI de ese usuario.

```powershell
./scripts/Start-Native.ps1 -WorkspaceDir C:/ruta/de/trabajo -DataDir C:/ruta/nueva/relayforge-staging -Port 8876 -AllowedHosts <host>.ts.net -AllowedLogins <login-tailscale> -PreviewPublicOrigin https://<host>.ts.net:8443
```

El script exige DataDir sin relayforge.db para evitar migrar accidentalmente otra instancia. Para reiniciar la instancia preparada, conservar las mismas variables RELAYFORGE_HOME/WORKSPACE_DIR/PORT y ejecutar `uv run relayforge serve`. No elimina datos. Mantener el Docker actual hasta aceptación nativa.

Defaults de conversación: RELAYFORGE_CHAT_AGENT=codex, RELAYFORGE_CHAT_MODEL=gpt-6-luna, RELAYFORGE_CHAT_EFFORT=medium. También settings.yaml admite chat_agent/chat_model/chat_effort. Cada conversación fija agente/modelo; las antiguas conservan Claude y su sesión. POST /api/conversations acepta `{}` o `{agent,model}` opcionales. La respuesta informa agent/model/runtime/capabilities. El arranque solo requiere la CLI del agente de chat predeterminado.

CH-01 Codex chat usa sandbox read-only. Ejecución de acciones y GUI se habilita en CH-03/CH-04; no anunciar esas capacidades todavía. El runtime nativo no concede elevación administrativa. Pairing, CSRF y allowlists siguen vigentes.

## Auditoría integrada

El hook admite únicamente dispatcher exacto, directorio y archivos del Job. El prompt muestra las cadenas autorizadas y exige cada check. Una denegación nativa, respuesta vacía, check omitido/fallido o hash cambiado bloquea el dictamen. No se modifica la configuración global de permisos automáticamente.


El perfil nativo admite `RELAYFORGE_ANTIGRAVITY_AUDIT_RUNNER`: ruta de confianza al runner compartido instalado por el operador (`-AuditRunner` en el script), cuyo dispatcher `relayforge-audit-check` ya está permitido. Esta ruta no se recibe desde el chat. Conserva el agente/modelo/esfuerzo, valida sus checks, gate y dictamen estructurado; una denegación bloquea el resultado. No instala otra regla global ni modifica el runner. Docker mantiene el adapter directo hasta configurar su propia vía acotada.

## Previews CH-06

El preview gateway usa su propio listener de loopback, por defecto el puerto `8793`; los servidores de preview usan el primer puerto libre de `8900-8999`. Configura `preview_gateway_port`, `preview_public_origin`, `preview_port_range`, `preview_idle_seconds` y `preview_max_active` en `settings.yaml` o con las variables `RELAYFORGE_PREVIEW_*`. El origen público debe ser HTTPS para abrir previews desde el teléfono. RelayForge no crea ni modifica reglas de Tailscale Serve.

Los procesos de preview se ejecutan como el usuario de Windows, dentro del directorio de la raíz aprobada, sin shell ni elevación. Conservan el entorno del usuario con `PORT`, `HOST=127.0.0.1` y `BROWSER=none`; no se instalan paquetes. Solo se admiten los ejecutables `npm`, `pnpm`, `yarn`, `node`, `python`, `py`, `uv`, `bun` y `deno`. Detén el preview cuando termines; también se detiene por inactividad, al cerrar/cancelar su Job o al cerrar el backend. Tras un reinicio se marca interrumpido y no se relanza automáticamente.

## Esfuerzo y herramientas (CH-07)

El esfuerzo predeterminado sale de `chat_effort`/`RELAYFORGE_CHAT_EFFORT`; cada conversación puede elegir otro nivel admitido y activar o desactivar herramientas desde la web (ver `docs/usage.md`). El turno guarda el esfuerzo y la política efectivos.

## Escritorio Windows (CH-04, bloqueado)

El worker GUI (`src/relayforge/desktop/worker.ps1`) se ejecuta como `powershell.exe -NoProfile -NonInteractive -File` sin cambiar la política de ejecución, con operaciones cerradas sobre UI Automation (`probe`, `launch`, `inspect`, `invoke`, `set_value`, `type_text`, `keys`, `capture`, `close`). Configuración: `desktop_enabled`, `desktop_apps` (predeterminado Bloc de notas), `desktop_allowed_dirs` (predeterminado `<RELAYFORGE_HOME>\desktop-files`) y `desktop_action_timeout`. RelayForge debe ejecutarse **sin elevación**: si el runtime está elevado, `launch` responde `runtime_elevated` y los objetivos elevados se rechazan con `target_elevated`. La conexión de estas acciones al agente del chat no está activa: la bloqueó el control de permisos del entorno de Claude y espera decisión del propietario (sección 15.14 del plan).

Los valores de identidad (host de la tailnet, logins permitidos y origen del preview) son propios de cada operador: pásalos por parámetro o variables de entorno, o guárdalos en un lanzador local `scripts/Start-Native.local.ps1`, excluido de Git, que invoque `Start-Native.ps1`. El script se niega a arrancar sin `AllowedHosts` y `AllowedLogins`. Usa `-AllowResume` para reutilizar un DataDir existente.
