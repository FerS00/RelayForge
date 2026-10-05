> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Especificación técnica — Fase 10

Estado: implementación local completada (2026-10-04); auditoría efectiva bloqueada por denegaciones del hook y cierre MVP pendiente de verificaciones físicas. Sin Claude por instrucción del usuario; Codex especifica e implementa, Antigravity auditor de solo lectura. Complejidad alta; esfuerzo efectivo Codex high y Antigravity high. Sin commit, push, publicación ni despliegue. Antigravity reportó APROBADO, 8/8 criterios y 12/12 comandos en el run `1a70f1650a454f2db514b690d0f59d33` (`gemini-3.8-flash-high`, high), pero `gate.ndjson` registra dos acciones denegadas; por la política del runner, el estado efectivo de auditoría es BLOQUEADO.

## Objetivo

Cerrar el endurecimiento del MVP: redactar secretos y rutas personales en datos persistidos/servidos; hacer explícitas las defensas CSP, Markdown y symlink; establecer CI para lint, tipos, pruebas, build, Gitleaks, rutas personales y Semgrep; completar la documentación de instalación, seguridad y contribución. Docker (D-17) se evaluará separadamente porque el Engine activo (`desktop-linux`) usa contenedores Linux y el runtime depende de APIs Windows/Job Objects.

## Rutas previstas

- `src/relayforge/security/{redact.py,personal_paths.py}`; `src/relayforge/db/{redacted.py,models.py}`
- `src/relayforge/api/{app.py,auth.py,sse.py}`; `src/relayforge/core/{chat.py,events.py,jobs.py}`
- `src/relayforge/process/supervisor.py`; `src/relayforge/adapters/claude/orchestrator.py`; `src/relayforge/git/worktrees.py`
- `web/src/components/{ChatView.tsx,ChatView.test.tsx}`; `web/package.json`, `web/package-lock.json`
- `tests/unit/{test_redact.py,test_redaction_persistence.py,test_personal_paths.py,test_supervisor.py,test_worktrees.py}`
- `tests/integration/{test_redaction.py,test_http_security.py,test_stream_sse.py}`; `tests/fakes/fake_agent.py`; fixtures JSONL sintéticas de Claude
- `.github/workflows/ci.yml`, `scripts/check_personal_paths.py`
- `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `docs/install-windows.md`, `docs/specs/FASE_10.md`, `docs/PLAN_PROYECTO.md`, `docs/ESTADO_TRABAJO.md`

## Contratos y criterios de aceptación

1. Un redactor con corpus cubre claves API comunes, bearer/JWT, bloques de clave privada, valores de credenciales por nombre y rutas personales Windows/macOS/Linux. Recursión JSON redacta valores sensibles sin alterar claves, tipos o texto ordinario.
2. Los mensajes, resúmenes, hallazgos, eventos persistidos y eventos SSE pasan por redacción antes de almacenamiento/emisión; el valor sintético de `.env` no aparece en datos API persistidos o servidos ni en los registros de eventos de la aplicación.
3. CSP declara explícitamente `default-src`, `script-src`, `style-src`, `connect-src`, `object-src`, `base-uri`, `form-action` y `frame-ancestors`; la UI muestra Markdown con `react-markdown` y `rehype-sanitize`, sin HTML crudo ni atributos/eventos ejecutables.
4. `WorktreeManager.diff` rechaza un path modificado cuyo destino resuelto sale del worktree; hay cobertura que no depende de privilegio Windows para crear symlinks y cobertura de symlink cuando el entorno la permite.
5. CI en GitHub Actions ejecuta Ruff, mypy, pytest con fakes, ESLint, TypeScript, Vitest, build web, Gitleaks, detector de rutas personales y Semgrep sobre código de producto. No usa CLIs reales de agentes ni publica artifacts con datos privados.
6. El detector de rutas personales tiene corpus permitido/bloqueado y no imprime la ruta encontrada. Gitleaks usa configuración y exclusiones justificadas solo para fixtures sintéticas.
7. README, SECURITY, CONTRIBUTING e instalación Windows describen comandos comprobados, límites S0, pairing/Tailscale, datos que se guardan y reportes de vulnerabilidad; no afirman despliegue Docker funcional sin una imagen construida/verificada.
8. Antigravity audita todos los criterios y ejecuta los checks locales declarados; se registra cada comprobación no ejecutada como pendiente. El runner no debe registrar acciones denegadas. **Estado:** checks ejecutados, pero auditoría bloqueada por las dos denegaciones de `gate.ndjson`.

## Verificación y estado de cierre

- Antigravity emitió APROBADO, 8/8 criterios y 12/12 comandos; no cambió fuentes. Sin embargo, `gate.ndjson` registra dos denegaciones: intento de leer un log interno fuera del alcance y búsqueda sobre el directorio `src/relayforge` no enumerado. `result.json` reporta `denied_actions=[]`, en contradicción con el gate. Conforme a `antigravity-audit`, el resultado efectivo queda BLOQUEADO; no se repitió con permisos ampliados.
- Python: Ruff, formato, mypy y pytest PASS; pytest 119 passed, 1 omitida por `WinError 1314` al crear un symlink privilegiado, y un aviso Starlette/httpx.
- Web: ESLint, TypeScript, Vitest (11 pruebas), build y `npm audit` PASS; 0 vulnerabilidades reportadas.
- Detector de rutas personales y Semgrep PASS (0 hallazgos); `git diff --check` PASS. El workflow YAML se parseó localmente con clave `on` conservada.
- No ejecutados: Gitleaks y actionlint locales (CLI ausente), GitHub Actions remoto (sin push autorizado), comprobaciones desde otro dispositivo/laptop, reinicio y CLIs reales. Las pruebas del repo usan fakes.
- Graphify actualizado tras los cambios de código: 1381 nodos, 2929 relaciones y 124 comunidades. El etiquetado automático intentó invocar Claude y falló por OAuth vencido; el grafo quedó generado con nombres genéricos.
- D-17: Docker CLI/Engine está activo en el contexto `desktop-linux` y `docker info` devuelve `linux`. El runtime importa APIs Win32/Job Objects; no se construyó una imagen Linux incompatible ni se cambió Docker Desktop. La imagen requiere que el usuario habilite un Engine de contenedores Windows compatible o autorice una adaptación del runtime.

## Límites

- El cierre de aceptación del MVP requiere las comprobaciones físicas de otro dispositivo/laptop y del reinicio, si forman parte de la sección 40.
- No se cambia el runtime de Windows a Linux ni se ajusta Docker Desktop/Engine automáticamente. No se declara funcional una imagen Docker hasta poder construirla y verificarla con un Engine compatible.
- No se ejecuta ZAP/Strix ni escaneo activo contra ningún servicio.

## Adenda D-17 — contenedor Windows

El usuario autorizó añadir una imagen Docker Windows y reinstalar Docker Desktop en modo all-users para usar contenedores Windows. La laptop es Windows 10 Pro; la imagen objetivo es `mcr.microsoft.com/windows/servercore:ltsc2019` con aislamiento Hyper-V. No se autoriza portar el supervisor Win32 a Linux.

Adenda operativa por el flujo móvil elegido: la imagen debe incluir Codex CLI y Antigravity CLI además de Claude Code para que `Nueva tarea` pueda ejecutar Claude → Codex → Antigravity. Versiones fijadas: Codex `0.159.2`, Antigravity `1.2.16` (SHA-512 comprobado); las sesiones del host no se copian. Codex usa un volumen persistente propio; el perfil de Antigravity queda bajo el volumen de perfil persistente ya usado por Claude. El login interactivo de ambos dentro del contenedor y la prueba real de Nueva tarea siguen siendo criterios pendientes hasta completarse.

Rutas añadidas al alcance: `Dockerfile.windows`, `compose.windows.yaml`, `docker.env.example`, `.dockerignore`, `pyproject.toml`, `uv.lock`, `src/relayforge/settings.py`, `src/relayforge/api/auth.py`, `src/relayforge/cli.py`, `tests/unit/test_settings.py`, `tests/integration/test_auth.py`, `README.md`, `docs/install-windows.md`, `docs/docker-windows.md`, `docs/PLAN_PROYECTO.md` y `docs/ESTADO_TRABAJO.md`.

Criterios: (1) la imagen instala runtime Windows y las dependencias reales de servidor y chat, incluidas las tres CLI; (2) el acceso al host sigue limitado al puente loopback `127.0.0.1:8792`; (3) el servidor dentro del contenedor acepta solo la IP exacta del gateway NAT como proxy confiable; (4) home, workspace, proyectos, perfil Claude/Antigravity y perfil Codex persisten en volúmenes; (5) allowlists se configuran fuera del repositorio, sin copiar credenciales del host; (6) build, health check, pairing, login de agentes y tarea real se informan por separado; (7) Antigravity audita el diff y los comandos autorizados. El servicio Linux `agent-ops` se detuvo y sus imágenes y volúmenes se respaldaron antes del cambio de Engine.

Estado al inicio de D-17: implementación y auditoría estática de la fase aprobadas; posteriormente el usuario autorizó instalar Windows containers, habilitar características y reiniciar la laptop. La actualización vigente de D-17 queda registrada a continuación y en `docs/ESTADO_TRABAJO.md`.

### Estado actualizado tras reinicio de Windows — 2026-10-04

- Docker Desktop 4.93.0 all-users usa Docker Engine 29.8.1, contexto `desktop-windows`, `OSType=windows`. Hyper-V y Containers están habilitados. El respaldo del Engine Linux se conserva y `agent-ops` sigue detenido.
- Construcción de `relayforge:windows` completada; Compose inicia `relayforge` en estado `healthy`. Claude Code 2.1.288 está instalado. Las allowlists JSON se validan y el volumen de Claude está separado.
- **Desviación del criterio 2:** Windows NAT no permite mapear el puerto a `127.0.0.1` (`Windows does not support host IP addresses in NAT settings`). Para no publicar el puerto en todas las interfaces, Compose no publica puertos host y asigna la IP estática `172.30.240.10` en una red NAT dedicada. Desde el host, `http://172.30.240.10:8792` responde HTTP 200; no existe listener host en 8792. El único gateway proxy confiable es `172.30.240.1`.
- Estado en la auditoría: Serve aún apuntaba a `http://127.0.0.1:8792`; después el usuario autorizó y se aplicó el cambio a `http://172.30.240.10:8792`. Desde el host, el backend NAT devuelve HTTP 200. La petición HTTPS al hostname tailnet resuelve y completa TLS, pero agotó 20 s sin respuesta HTTP; acceso móvil con Docker pendiente.
- Después de actualizar los documentos y regenerar Graphify, la imagen se reconstruyó y Compose recreó el servicio. Verificación final: `relayforge` healthy en `172.30.240.10`, cuatro volúmenes, cero reinicios, sin puertos Docker, HTTP directo 200 y Claude Code 2.1.288. Graphify: 1669 nodos, 3516 relaciones y 125 comunidades.
- Pendiente: no se harán más ciclos de auditoría en esta ejecución (máximo de tres alcanzado). Login Claude fue completado dentro del contenedor; faltan pairing, creación de conversación y stream desde el móvil. Build, health check y HTTP local host→contenedor son verificaciones distintas; ninguna cuenta como prueba móvil.


### Corrección del acceso por Tailscale — 2026-10-05

- El proxy Serve configurado directamente a `172.30.240.10:8792` completaba TLS pero no devolvía HTTP. La documentación de Tailscale limita sus proxies HTTP a backends `http://127.0.0.1`; se comprobó que el backend NAT directo era incompatible con el proxy.
- Con autorización del usuario, se añadió una regla persistente `127.0.0.1:8792 → 172.30.240.10:8792` con Windows `portproxy` y Serve se cambió a `http://127.0.0.1:8792`. La regla escucha solo en loopback; Compose sigue sin publicar puertos.
- Verificación: HTTP loopback 200; HTTPS tailnet `/` y `/api/auth/status` 200; Playwright carga «Emparejar RelayForge»; `claude auth status` confirma login en el contenedor; RelayForge continúa healthy. Pairing y flujo de conversación/SSE en celular no ejecutados todavía.

### Auditoría final de D-17 — ciclo 3

- Antigravity `gemini-3.8-flash-high`, esfuerzo `high`, run `d6c0d47b02ee4b96bc899f68ea04f62c`: informe APROBADO, 14/14 checks exitosos, sin cambios de fuentes.
- El informe y `result.json` indican `denied_actions=[]`, pero `gate.ndjson` contiene una denegación de `manage_task` al consultar el estado de una subtarea. Por la regla del runner, la auditoría efectiva queda **BLOQUEADA** pese al resultado textual aprobado. No se amplió el permiso ni se sustituyó el auditor; se alcanzó el máximo de tres ciclos.
- Persisten como pruebas físicas pendientes el login interactivo inicial de Claude y el pairing/navegación móvil. Serve ya se cambió tras autorización expresa; la petición HTTPS desde el mismo host tuvo timeout y requiere verificación desde el móvil.
