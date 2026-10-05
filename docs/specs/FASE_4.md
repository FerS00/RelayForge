> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Fase 4 — Acceso remoto y diagnóstico

Estado: **Implementación auditada APROBADA; validación externa parcial** (actualizado 2026-10-05). Pairing móvil y prueba de identidad desde segunda PC completados tras corregir Uvicorn. La emulación móvil confirmó creación tras renovar CSRF; falta reiniciar el backend del puerto 8792 y confirmar el SSE actualizado desde el móvil. Reinicio físico de laptop y comparación PC↔laptop siguen pendientes. Auditorías y verificaciones previas se detallan abajo.

## ESPECIFICACIÓN TÉCNICA (PARA CODEX)

### Ajuste de cierre: CSRF renovable para sesiones persistentes (2026-10-05)

- Rutas: `web/src/api.ts`, `web/src/App.tsx`, `web/src/components/ConversationList.tsx`, pruebas `web/src/api.test.ts` y `web/src/App.test.tsx`, `src/relayforge/api/app.py`, `src/relayforge/api/auth.py`, `tests/integration/test_auth.py`, este documento y checkpoint.
- Problema: pairing fija cookie CSRF durante 600 segundos, la sesión dura 14 días, y la capa API no vuelve a solicitar un nonce. Las mutaciones posteriores al vencimiento fallan con `csrf_rejected`; la mutación de crear conversación no muestra su error.
- Comportamiento: cada método mutante obtiene un nonce CSRF nuevo desde `GET /api/auth/csrf`, usa la cookie recién puesta y envía el mismo valor en `X-CSRF-Token`. Peticiones simultáneas comparten la renovación en vuelo. Los errores de creación se muestran como alerta en bienvenida y barra lateral.
- Criterios: (1) al crear conversación, la web renueva CSRF antes del POST y reintenta nada; (2) nonce/cookie/header coinciden; (3) el error de API al crear conversación aparece visible; (4) las rutas GET no solicitan CSRF; (5) Vitest, lint, typecheck y build pasan.

### Ajuste de cierre: SSE en EventSource same-origin (2026-10-05)

- Causa observada en emulación móvil: el navegador abrió `GET /api/stream` sin `Origin`; el middleware lo rechazó con 403 aunque la página y el SSE compartían origen.
- Regla: aceptar Origin exacto si viene presente; cuando falta, aceptar únicamente `Sec-Fetch-Site: same-origin`. Mantener autenticación, Host y rechazo de Origin incorrecto, y rechazar metadata cross-site o ausente.
- Verificación local y auditoría: `tests/integration/test_auth.py` 12 passed; web 15 passed; ESLint, TypeScript, build, Ruff, mypy y diff-check PASS. Antigravity APROBADO, 8/8 comandos, sin denegaciones ni cambios, run `9f415ae9b68247e3bfb169314f788fcb`, modelo `gemini-3.8-flash-high`, esfuerzo `high`.
- El flujo de creación móvil con CSRF vencido navegó a la conversación, pero fue antes de esta corrección SSE. La comprobación del stream tras reiniciar el backend sigue pendiente.

### Objetivo

Proteger toda la API con pairing de un solo uso, cookie de sesión y CSRF; mantener el backend enlazado únicamente a `127.0.0.1`; exponer diagnóstico local sin secretos; y dejar documentado el inicio automático en Windows. El despliegue en laptop y las pruebas desde otro dispositivo son pasos manuales y no se consideran completados por pruebas locales.

### Rutas afectadas

- `src/relayforge/settings.py`: configuración de bind, logins Tailscale permitidos y hosts públicos exactos.
- `src/relayforge/cli.py`: comandos `token pair`, `doctor [--fingerprint|--compare]` y guardia de bind.
- `src/relayforge/api/auth.py`: pairing, sesiones, identidad Tailscale, CSRF, cookie y verificación de origen.
- `src/relayforge/api/app.py`, `src/relayforge/api/routes/auth.py`, `src/relayforge/api/routes/doctor.py`: middleware y rutas protegidas.
- `src/relayforge/core/auth.py`, `src/relayforge/doctor/{__init__.py,checks.py}`: servicios de autenticación y diagnóstico.
- `src/relayforge/db/models.py`, `src/relayforge/db/migrations/versions/0004_auth.py`: códigos de pairing y sesiones revocables.
- `web/src/{App.tsx,api.ts}`, `web/src/pages/{Pairing,Agents}.tsx`, `web/src/pages/Pairing.test.tsx`, `web/src/styles.module.css`: pairing y estado de agentes.
- `scripts/register-task.ps1`, `docs/install-windows.md`: registro opcional de tarea programada y guía; no ejecutar el script durante esta fase.
- `tests/conftest.py`, `tests/integration/test_auth.py`, `tests/integration/test_doctor.py`, `tests/unit/test_settings.py`, `tests/unit/test_cli.py`, `tests/integration/test_db_migrations.py`.
- Este documento, `docs/PLAN_PROYECTO.md` y `docs/ESTADO_TRABAJO.md` para estado y evidencia.

### Contratos y reglas

Corrección autorizada durante las pruebas de cierre (2026-10-04): `src/relayforge/cli.py` debe iniciar Uvicorn con `proxy_headers=False` para conservar el peer TCP real. La identidad se acepta solo del proxy loopback; `expected_origin()` ya procesa `X-Forwarded-Proto` cuando el peer es confiable. Regresión en `tests/integration/test_auth.py`: usando la configuración real del CLI, un peer loopback con `X-Forwarded-For` remoto permite pairing con login autorizado; un peer remoto con `X-Forwarded-For: 127.0.0.1` sigue rechazado. Se mantienen sesión, allowlist, Origin y CSRF.

1. `RELAYFORGE_BIND` solo acepta `127.0.0.1`; cualquier otro valor hace fallar el arranque. El listener continúa enlazado explícitamente a loopback.
2. La lista `RELAYFORGE_ALLOWED_TAILSCALE_LOGINS` y `RELAYFORGE_ALLOWED_HOSTS` se parsea como entradas separadas por coma, se normaliza a minúsculas y no admite comodines. Si está vacía, el pairing remoto falla cerrado.
3. `relayforge token pair` genera un secreto aleatorio de un solo uso, persiste únicamente su hash y muestra el valor una vez. El hash se invalida atómicamente después de un pairing exitoso o al expirar.
4. `GET /api/auth/csrf` crea un nonce aleatorio con cookie legible `rf_csrf` y devuelve el mismo nonce. `POST /api/auth/pair` requiere nonce en cookie y encabezado, código válido y `Tailscale-User-Login` en allowlist. El éxito crea sesión aleatoria con hash persistido y cookie `rf_session` con `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/` y `Max-Age` finito.
5. Toda ruta `/api` salvo `GET /api/auth/status`, `GET /api/auth/csrf` y `POST /api/auth/pair` requiere sesión válida y login Tailscale permitido. Cualquier mutación requiere Origin exacto permitido y CSRF doble envío. `GET /api/stream` además requiere Origin exacto permitido. La cabecera de identidad solo se acepta del proxy local; no se confía en cabeceras de clientes de red.

Enmienda durante pruebas de cierre: los navegadores omiten `Origin` en solicitudes GET same-origin de `EventSource`. Para `GET /api/stream`, se acepta `Origin` exacto o, si está ausente, `Sec-Fetch-Site: same-origin`; la sesión Tailscale sigue siendo obligatoria y las solicitudes cross-site o sin metadatos se rechazan. Las mutaciones mantienen Origin exacto y CSRF doble envío.
6. Hosts válidos son `localhost`, `127.0.0.1` y los hosts exactos configurados. Un `Host` ausente, inválido o no configurado se rechaza. No se habilita CORS.
7. `POST /api/auth/logout` revoca la sesión y limpia cookies. Los IDs y secretos no aparecen en logs, respuestas de error ni URLs.
8. `relayforge doctor` comprueba Git, Tailscale, Docker como información opcional, espacio, integridad SQLite, bind, protección del secreto y disponibilidad/autenticación/versiones de las CLIs mediante comandos de estado de solo lectura y timeout. No usa `--deep` automáticamente.
9. `doctor --fingerprint` escribe JSON determinista sin rutas personales, tokens ni estado de autenticación; `doctor --compare <archivo>` informa solo diferencias. Las comprobaciones indisponibles se etiquetan `UNKNOWN`, no como PASS.
10. La tarea programada se instala solo para el usuario actual, sin elevación ni ejecución bajo credenciales almacenadas; el script no altera Tailscale, firewall, suspensión o credenciales. La selección entre inicio de sesión e inicio del sistema y la disponibilidad de las CLIs se informa como pendiente de POC-10.

### Criterios de aceptación

1. Pairing válido crea sesión; código incorrecto, vencido, repetido o login no permitido no crea sesión.
2. API, POST y SSE rechazan sesión ausente/revocada, identidad no permitida, Host u Origin incorrectos y CSRF ausente/incorrecto.
3. Cookie de sesión tiene los atributos especificados; logout la revoca; el backend solo enlaza a `127.0.0.1`.
4. `doctor` informa resultados identificables y `--fingerprint/--compare` excluyen secretos y rutas personales.
5. La UI solicita pairing cuando no hay sesión y muestra el estado de agentes cuando sí la hay.
6. El script y la guía describen instalación reversible sin ejecutarse sobre la laptop.
7. Ruff, formato, mypy, pytest, lint, typecheck, Vitest, build y `git diff --check` pasan; Antigravity audita la especificación y diff en solo lectura.
8. El pairing real desde un dispositivo Tailscale no emparejado, la falsificación externa de cabeceras, el reinicio de laptop y la comparación de fingerprints PC↔laptop permanecen pendientes hasta ejecución manual y evidencia.

### Verificación manual iniciada (2026-10-04)

- AC-01 — versiones observadas: laptop y PC tienen Tailscale `1.102.4`, Antigravity `1.2.16` y Codex CLI `0.159.2`. Codex se encontró fuera del PATH en la PC, bajo `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe`. Git difiere (`2.55.0.windows.3` laptop; `2.51.0.windows.1` PC) y Claude difiere (`2.1.288` laptop; `2.1.283` PC). `doctor --compare` compara las versiones de agentes del fingerprint, no Git/Tailscale; Claude sigue siendo discrepante.
- `uv run relayforge doctor` en la laptop pasó bind (`127.0.0.1`), Git, Tailscale, Docker, DB y disponibilidad de las CLIs. Claude `2.1.288` devolvió `AUTH_REQUIRED`; Codex `0.159.2` devolvió `AVAILABLE`; agy `1.2.16` queda `UNKNOWN` para autenticación porque el probe implementado solo comprueba versión. La DB ya estaba en la revisión actual `0007_job_reliability`.
- Resultado provisional: **Fallido** para paridad de CLIs por Claude; Git queda como diferencia informativa. La autenticación de Claude en laptop está confirmada como requerida y la de agy no se puede confirmar con el probe actual. `doctor` no expuso rutas ni logins en la salida registrada.
- Preparación API/Tailscale (laptop): `%LOCALAPPDATA%\RelayForge\config\settings.yaml` existe y valida; workspace/projects root existentes, bind loopback, 2 logins y 1 host permitidos. No se guardaron sus valores en el informe.
- Tailscale `BackendState=Running`, nodo local online. Serve HTTPS ya apunta a loopback puerto 8792 (sin evidencia de Funnel en `serve status`). Puerto 8792 estaba libre; puerto 8787 pertenece a otra app y `/api/auth/status` responde 404.
- RelayForge iniciado desde este worktree en `127.0.0.1:8792` usando `--port 8792` temporal, sin cambiar settings ni Serve. Local `/api/auth/status` = 200 con `authenticated=false`; local `/api/agents` = 401. A través del host HTTPS configurado, `/api/auth/status` = 200 y la validación TLS pasó.
- Prueba desde móvil (2026-10-04; hostname anonimizado): conectado desde otro nodo, `GET https://laptop.nombre-tailnet.ts.net/api/agents` devolvió `401` y `{"error":{"code":"authentication_required","message":"Se requiere pairing."}}`. Resultado esperado: se confirma el acceso HTTPS al backend y el rechazo sin sesión. No demuestra que la identidad Tailscale llegue a la aplicación ni completa el pairing.
- Intento inicial de pairing desde el móvil: la UI mostró `Identidad no permitida.`. Después se reprodujo que Uvicorn reescribía la dirección del peer local con `X-Forwarded-For`; la corrección y el resultado del nuevo pairing constan abajo. No se modificaron allowlists adicionales.
- El usuario informó login exitoso desde el móvil (2026-10-04). SQLite registró primero una sesión activa y un código consumido.
- Desde la segunda PC, el usuario envió la cabecera falsa `Tailscale-User-Login: spoof.invalid@example.test` junto con un código de pairing real; el servidor respondió HTTP 200. SQLite quedó con dos sesiones activas, el login de la sesión más reciente pertenece a la allowlist y el login falso no está permitido. Evidencia compatible con que Tailscale Serve reemplazó la cabecera del cliente por la identidad autenticada; el código real emparejó también esa PC y quedó consumido. La prueba de spoofing externo queda **PASS** según esta evidencia. No equivale a observar independientemente el contenido de `GET /api/agents` en el móvil.
- Reinicio de laptop, comparación PC↔laptop y verificación visual siguen pendientes. PC aún no tiene configuración RelayForge para `doctor`.

### Corrección del rechazo de identidad durante pairing (2026-10-04)

- Hallazgo Alto, categoría autenticación/integración: Uvicorn activaba `proxy_headers=True` por defecto y reemplazaba el peer TCP loopback por `X-Forwarded-For`. `trusted_proxy()` entonces rechazaba la identidad que entregaba Tailscale Serve, incluso con login autorizado y código válido. La regresión contra la configuración real del CLI reprodujo `403 identity_denied` antes del cambio.
- Corregido el arranque con `proxy_headers=False`, conservando el peer real y las comprobaciones de identidad, sesión, Host, Origin y CSRF. Prueba parametrizada: proxy local con dirección remota reenviada permite pairing, status autenticado y lectura de agentes; peer remoto que falsifica localhost sigue rechazado.
- Verificación de Codex: 16 pruebas de auth/HTTP/CLI PASS; Ruff, formato y mypy (78 fuentes) PASS. La primera ejecución tuvo un error preexistente de limpieza del temporal global de pytest; el auditor usó un temporal dedicado y no tuvo ese error. Persiste un aviso de deprecación Starlette/httpx.
- Auditoría puntual de Antigravity APROBADA: run `bc3f63e5f3e9465282619d6cc485a5fa`, `gemini-3.8-flash-high`, esfuerzo high, 5/5 criterios, 5/5 checks, cero denegaciones y cero cambios de fuentes. Este pase no cierra el gate bloqueado de Fase 10.
- Estado global de esta corrección: **Aprobado con observaciones**; login móvil confirmado, sesión válida registrada y spoofing desde segunda PC PASS. Falta reinicio de laptop, comparación PC↔laptop y comprobación visual autenticada.

### Dependencias y exclusiones

Fase 3; POC-10 y POC-11. Esta implementación no registra tareas, no cambia la laptop, no abre puertos, no configura Tailscale ni realiza pairing externo. El token pairing requiere configurar allowlists y reenviar el host HTTPS de Tailscale Serve; sin esa configuración remota, el servidor falla cerrado.
