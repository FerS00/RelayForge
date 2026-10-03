# Resultados de las POCs — Fase 0

- Plan: `docs/PLAN_PROYECTO.md` (Fase 0). Especificación: `docs/specs/FASE_0A.md` (con las adendas 1 y 2).
- Fecha: 2026-10-02. Máquina: PC principal, Windows 11 (10.0.26300), Python 3.13.15 (venv de `pocs/`), Git 2.51.0.
- Versiones de agentes: Claude Code 2.1.283, codex-cli 0.159.2, agy 1.2.15.
- La evidencia cruda (redactada) está en `pocs/results/<poc>/<timestamp>/`, ignorado por Git. Se cita aquí el directorio de cada ejecución relevante.
- Ejecutó: el coordinador (Claude), fuera del sandbox, salvo cuando se indica otra cosa.

## Resumen

| POC | Estado | Decisión que desbloquea |
|---|---|---|
| POC-01 Claude → stream-json | **PASS** (C3 y C4 validados manualmente, ver notas) | Contrato de `ClaudeAdapter` (Fase 1) |
| POC-02 Codex → eventos | **PASS** (C2 validado manualmente) | Contrato de `CodexAdapter` (Fase 3) |
| POC-03 Antigravity de solo lectura | **PASS** (normal y schema); barrera de escritura **confirmada** en un experimento dirigido | Diseño del `AuditorAdapter`: el auditor no ejecuta comandos (ADENDA 2) |
| POC-05 Worktrees | **PASS** (6/6) | Git service (Fase 3) |
| POC-06 Cancelación | **PASS** (sintético 10/10; Claude, Codex y agy reales) | Supervisor de procesos con Job Objects |
| POC-04 Herramientas MCP de RelayForge | **PASS** (9/9) | Sección 17: shim MCP + token; restricción de Bash |
| POC-07 Caída del backend | **PASS** en A, B y B-early; C5 no concluyente (ver notas) | Sección 25: procesos desacoplados, reconciliación, `not_resumable` |
| POC-08 Aprobación humana | **PASS** (C1-C10) | Sección 20 + `--permission-prompt-tool` para aprobaciones remotas |
| POC-09 Salud de agentes | **PASS** (5/5) | `doctor` / Agents status |
| POC-10 Arranque automático | Línea base interactiva en la PC: **PASS**. Modos de tarea programada en la laptop: **pendientes (requieren acción del usuario)** | Fase 4 |
| POC-11 Tailscale serve | Parte local en la PC: **PASS** (riesgo de falsificación confirmado). `tailscale serve` + móvil: **pendiente (requiere autorización)** | Fase 4, autenticación |

## POC-01 — Claude Code stream-json

Evidencia: `pocs/results/poc01_claude_stream/20261002-215900/`, `…/20261002-220126*` y la última ejecución, además de un experimento manual con `--json-schema`.

| Supuesto | Resultado | Estado |
|---|---|---|
| `-p --output-format stream-json` requiere `--verbose` | Sin él: `Error: When using --print, --output-format=stream-json requires --verbose` | **CONFIRMED** |
| Eventos incrementales | Primera línea en ~1,4-1,5 s; 24-25 eventos antes del resultado | **CONFIRMED** |
| Texto del asistente en streaming | Llega por mensaje completo (6-25 s), no por token. Para recibir deltas hará falta `--include-partial-messages` (no probado) | NEEDS POC (Fase 1) |
| `--session-id` + `--resume` conservan el contexto entre procesos | El turno 2 respondió `AZUL-7` | **CONFIRMED** |
| `--json-schema` | Resultado en `result.structured_output` (dict) y `result.result` (str JSON). **Rechaza** esquemas con `$schema` draft 2020-12 | **CONFIRMED** |
| Skills, MCP y CLAUDE.md activos en `-p` | El evento `system/init` lista 101 skills, 19 servidores MCP, 149 slash commands, 115 herramientas, `agents`, `permissionMode` y `model` | **CONFIRMED** |
| El evento `result` es la última línea | **No**: después llega `system/task_summary`. Hay que buscar el evento `type=="result"` | **CONFIRMED** (lección para el parser) |
| Rate limits observables | Evento `rate_limit_event` con `status`, `resetsAt`, `rateLimitType` y `unifiedWindows.{five_hour,seven_day}.utilization` | **CONFIRMED** (adelanta POC-09) |
| Coste y uso | `result.modelUsage` (tokens, `costUSD`), `ttft_ms`, `duration_ms` | **CONFIRMED** |
| Hooks del usuario | Eventos `system/hook_started` y `hook_response` (SessionStart) | **CONFIRMED** |

Notas:
- C3 dio FAIL en la última ejecución por el defecto del runner (toma el último evento); la salida estructurada era válida (verificado a mano). En la ejecución anterior fue PASS.
- C4 (skills) quedó en MANUAL antes de la corrección 4; tras ella fue PASS.

## POC-02 — Codex `exec --json`

Evidencia: `pocs/results/poc02_codex_events/20261002-220418/` y `…/20261002-220707/`.

| Supuesto | Resultado | Estado |
|---|---|---|
| JSONL `thread.started` → `turn.started` → `item.*` → `turn.completed` (con `usage`) / `turn.failed` | Observado | **CONFIRMED** |
| `item.type` útiles | `file_change` (`changes[{path absoluto, kind}]`), `command_execution` (`command`, `aggregated_output`, código), `agent_message` | **CONFIRMED** |
| Ruido de configuración | 38 `item.type=="error"` al arrancar: roles TOML mal formados en `~/.codex/agents` y MCP caído (`localhost:64342`). **No son fallos de la tarea** | **CONFIRMED** (el adapter debe tratarlos como advertencias) |
| `--output-schema` | Exige un esquema **estricto**: `additionalProperties:false` y todas las propiedades en `required`. Si no, `turn.failed` con 400 `invalid_json_schema`. Con un esquema estricto, el último `agent_message` y `-o` contienen JSON válido | **CONFIRMED** |
| Flag `--effort` | **No existe**. Se usa `-c model_reasoning_effort="high"` | **CONFIRMED** |
| `exec resume <thread_id>` en un proceso nuevo con `-c sandbox_mode=…` | Funcionó y aplicó el segundo cambio | **CONFIRMED** |
| Git dentro del sandbox | Codex informó que `git` no puede lanzar `sh` en el sandbox → el diff debe calcularlo RelayForge desde fuera | **CONFIRMED** |
| Repositorio principal intacto | `git status` previo == posterior | **CONFIRMED** |
| **Codex lee la configuración global del usuario dentro del worktree** | Leyó `~/.codex/memories/MEMORY.md` y skills (`plan-driven-development`, **`antigravity-audit`**) | **CONFIRMED** → el riesgo de la sección 0.3 del plan también afecta a Codex. Confirma además la limitación S0 (lectura fuera del worktree) |

## POC-03 — Antigravity auditor de solo lectura

Evidencia: `pocs/results/poc03_antigravity_audit/20261002-2206*` (primer diseño) y `…/20261002-2211*` (ADENDA 2), más un experimento de barrera.

| Supuesto | Resultado | Estado |
|---|---|---|
| Hooks `PreToolUse` en `.agents/hooks.json` del cwd con payload `{"toolCall":{name,args}}` | El gate recibió y decidió todas las llamadas | **CONFIRMED** |
| `run_command` permitido solo con el hook | **No**: agy exige además `permissions.allow` con `command(regex:…)` en su `settings.json` **global** (`~/.gemini/antigravity-cli/settings.json`). Una regla en `.agents/settings.json` del cwd no se respeta | **CONFIRMED** |
| Comportamiento ante una denegación **nativa** de agy en headless | **Aborta el turno**: `status=SUCCESS`, `response` vacío y `denied_actions=[{"action":"command"}]`. agy intenta comandos por iniciativa propia (por ejemplo `Get-ChildItem`) si el prompt no lo prohíbe | **CONFIRMED** |
| Comportamiento ante una denegación del **hook** de RelayForge | **No aborta**: el agente continúa y lo informa | **CONFIRMED** |
| Barrera de escritura | Prompt que ordenaba editar o crear archivos: agy intentó `write_to_file` y `replace_file_content` (en `--mode plan` y en `accept-edits`) → el gate denegó las 6 llamadas de escritura; los archivos quedaron intactos | **CONFIRMED** |
| Auditoría sin comandos (ADENDA 2) | `normal`: `ESTADO: APROBADO` con hallazgos archivo:línea, 5 `view_file` permitidos, hashes intactos, `check-0.json` leído | **CONFIRMED** |
| `--json-schema` en agy | La respuesta siguió siendo texto; el veredicto se obtuvo de la línea `ESTADO:` | **NO CONFIRMADO** (no fiable; usar `ESTADO:`) |
| Caso `tamper` mediante el prompt de auditoría | El modelo se negó a editar por sí mismo; ninguna barrera llegó a actuar → no concluyente; sustituido por el experimento dirigido | Ver fila de barrera |

## POC-05 — Worktrees

Evidencia: `pocs/results/poc05_worktree/20261002-220126/`. Repositorio sandbox con submódulo local, LFS y un cambio sin commit.

PASS en C1-C6: worktree creado en `C:\RF\poc\…`, repositorio principal intacto (incluido el cambio sin commit), diff con los dos archivos, ruta de 294 caracteres funcional con `core.longpaths`, submódulo inicializado, limpieza completa (`remove` + `prune`).

Observaciones:
- Git avisa `LF will be replaced by CRLF` (por `core.autocrlf` del usuario). RelayForge deberá fijar el comportamiento de fin de línea por worktree (decisión para la Fase 3).
- La rama del worktree queda tras `remove`; la política de limpieza debe decidir si borrarla.

## POC-06 — Cancelación con Job Objects

| Caso | Descendientes en el momento de cancelar | Supervivientes | Tiempo |
|---|---|---|---|
| Sintético (python → 2 hijos → nietos), 10 iteraciones | ≥5 | 0 (10/10) | < 5 s |
| Claude Code real | **67** (`cmd.exe`, `uvx.exe` de servidores MCP, …) | 0 | 0,08 s |
| Codex real | (runner) | 0 | — |
| agy real | 4 (`cmd.exe`, `node.exe`) | 0 | 0,05 s |

**CONFIRMED**: `CreateJobObject` + `CREATE_SUSPENDED` + `AssignProcessToJobObject` + `TerminateJobObject` elimina árboles completos de las tres CLIs, incluidos sus servidores MCP.

## POC-04 — Herramientas MCP de RelayForge para Claude

Evidencia: `pocs/results/poc04_mcp_tools/20261002-230130/` (PASS).

| Supuesto | Resultado | Estado |
|---|---|---|
| Un servidor MCP stdio propio se carga con `--mcp-config` **junto a** los MCP del usuario | `system/init.mcp_servers`: `relayforge` `connected` y los demás servidores presentes | **CONFIRMED** |
| El shim MCP → API HTTP local con token Bearer | Llamadas a `get_job_status` y `propose_job` con `auth_ok=true`; el token no aparece en ningún artefacto (CS) | **CONFIRMED** |
| `--allowed-tools mcp__relayforge__<tool>` habilita herramientas MCP en `-p` | Funciona | **CONFIRMED** |
| `--disallowed-tools` bloquea `codex` en Bash con Bash general permitido | `Bash(codex:*)` y `Bash(codex *)` funcionan; `echo` se ejecuta y `codex --version` se deniega (`result.permission_denials[{tool_name, tool_use_id, tool_input}]` y el `tool_result` «Permission to use Bash with command … has been denied.») | **CONFIRMED** |
| La instrucción `--append-system-prompt` frena la delegación por skills | Claude se negó a usar `codex-delegate`; eso es obediencia del modelo, no una barrera. La barrera real es el bloqueo de Bash | **CONFIRMED** (como complemento) |
| SDK MCP de Python | Está instalado **mcp 2.3.0**: `FastMCP` pasó a llamarse `MCPServer` (`mcp.server.mcpserver`) | **CONFIRMED** |
| Modo de permisos heredado | Sin `--permission-mode`, Claude hereda el modo global del usuario (`auto`, con clasificador). RelayForge debe fijarlo siempre | **CONFIRMED** |

## POC-07 — Caída del backend con un agente vivo

Evidencia: `pocs/results/poc07_backend_restart/20261002-230130/`.

| Escenario | Resultado | Estado |
|---|---|---|
| A: se mata el supervisor y el agente (Claude) sigue vivo; el nuevo supervisor continúa leyendo desde el offset | El agente terminó solo; 36/36 líneas procesadas sin huecos ni duplicados (`JobObject(kill_on_close=False)` + stdout a archivo) | **CONFIRMED** |
| B: reinicio completo (supervisor y agente muertos tras el primer `assistant`) → `interrupted` → `--resume` | Reconciliación `interrupted`; la reanudación recordó `VERDE-42` | **CONFIRMED** |
| B-early: el agente muere antes de su primer mensaje de modelo | `--resume` devuelve `result.subtype=error_during_execution` con `errors=["No conversation found with session ID: …"]` → `not_resumable` | **CONFIRMED** (hay que reintentar el paso, no reanudar) |
| C5 (sin procesos remanentes) | Un PID del escenario A figuraba vivo al final; el runner no comparaba `create_time` y lo terminó → no concluyente. Experimento aparte: Claude sale ~2,4 s después de emitir `result`, sin hijos vivos | No concluyente → regla de diseño: tras el evento final, periodo de gracia y después `TerminateJobObject`, siempre con PID + `create_time` |

## POC-08 — Aprobación humana

Evidencia: `pocs/results/poc08_approval/` (última ejecución PASS).

| Supuesto | Resultado | Estado |
|---|---|---|
| La aprobación pendiente sobrevive al reinicio del servidor (SQLite WAL) | C1 | **CONFIRMED** |
| La decisión es idempotente: la misma clave repite el resultado sin repetir el efecto; otra clave da 409 | C2-C4 | **CONFIRMED** |
| «Approve for job» autoaprueba la misma operación en el mismo job y no se extiende a otros jobs; rechazar → `FAILED` sin efecto | C5-C7 | **CONFIRMED** |
| `--permission-prompt-tool mcp__rfperm__approval_prompt` consulta a RelayForge | Entrada recibida: `{tool_name: "Write", input: {file_path, content}}`. Respuesta `{"behavior":"allow","updatedInput":…}` → archivo creado; `{"behavior":"deny","message":…}` → no creado y denegación visible | **CONFIRMED** |
| Formato de la respuesta de la herramienta | Debe ser **un único bloque de texto**: en mcp 2.x hace falta `@server.tool(structured_output=False)`; si no, Claude responde «Permission prompt tool returned an invalid result» | **CONFIRMED** |
| Qué consulta la herramienta | Los comandos Bash de solo lectura (p. ej. `echo`) se aprueban automáticamente sin consulta (C10); `Write` sí consulta | **CONFIRMED** → la política de RelayForge no puede depender solo del permission prompt; se combina con `--disallowed-tools` |

## POC-09 — Salud de agentes

Evidencia: `pocs/results/poc09_health/` (última ejecución PASS). La primera ejecución guardó el email y el `orgId` de la cuenta; esa evidencia se borró y el redactor ahora cubre `email`, `orgId`, `orgName` y `accountId`.

| Señal | Resultado | Estado |
|---|---|---|
| Claude `auth status` | JSON con `loggedIn` (código 0 si hay sesión, 1 si no); `CLAUDE_CONFIG_DIR` vacío → `loggedIn:false` | **CONFIRMED** |
| Codex `login status` | `Logged in using ChatGPT` (0) / `Not logged in` (1, con `CODEX_HOME` vacío) | **CONFIRMED** |
| agy | No tiene comando de estado; redirigir `USERPROFILE`/`HOME` no cambia su autenticación → solo una sonda mínima `-p` (`--deep`) | **CONFIRMED** |
| NOT_INSTALLED | `locate()` con PATH vacío → `missing` en las 3 | **CONFIRMED** |
| `claude doctor` / `codex doctor` | Ejecutables sin interacción; `codex doctor` resume `N ok · N warn · N fail` | **CONFIRMED** |
| Rate limits | Claude: `rate_limit_event`. Codex y agy: ninguna señal observada en el uso normal (solo `usage`) | Claude CONFIRMED; Codex/agy NEEDS POC (cuando se alcance un límite real) |

Observaciones del entorno del usuario (no son defectos de RelayForge): `codex doctor` informa de 19 roles de agente en `~/.codex/agents/*.toml` con `invalid transport`, `ripgrep` no verificable, una sugerencia de exclusiones de Defender y el MCP de JetBrains inaccesible.

## POC-10 — Arranque automático (parte ejecutada)

- Línea base interactiva en la PC (`probe.py --deep`, sesión 1): Claude, Codex y agy `AVAILABLE`, con las sondas profundas correctas; la evidencia no contiene datos personales.
- **Pendiente en la laptop:** registrar la tarea en los modos `Logon`, `StartupS4U` y `StartupPassword` (`register-task.ps1`), reiniciar y comparar con la línea base. Lo ejecuta el usuario (requiere reiniciar la laptop y, en un modo, introducir su contraseña).

## POC-11 — Tailscale serve (parte ejecutada)

- `app.py` escucha solo en `127.0.0.1:8792` (verificado con `Get-NetTCPConnection`).
- **Hallazgo de seguridad confirmado:** cualquier proceso local puede enviar `Tailscale-User-Login: attacker@example.com` a `127.0.0.1` y la app lo acepta (`spoof_accepted_direct=true`). Como los agentes se ejecutan en la misma máquina, **la identidad por cabeceras de Tailscale no es suficiente**: la sesión emparejada con cookie (`HttpOnly`, `SameSite=Strict`) y el CSRF son obligatorios, y las cabeceras quedan como capa adicional.
- La tailnet incluye un nodo de otro usuario (compartido), así que la allowlist de identidad es necesaria (T9).
- **Pendiente:** `tailscale serve --bg 8792` en la laptop, `/whoami` y un SSE de 10 min desde el móvil, y después `tailscale serve reset`. Requiere autorización del usuario (cambia la configuración de Tailscale del nodo).

## Decisiones y cambios para el plan

1. **El auditor no ejecuta comandos** (ADENDA 2): RelayForge (CheckRunner) ejecuta los checks antes de auditar y entrega los resultados como evidencia de solo lectura. El prompt del auditor debe prohibir explícitamente los comandos, porque una denegación nativa aborta el turno.
2. **Parsers por tipo, no por posición**: `type=="result"` (Claude), `event=="result"` (agy) y `turn.completed/failed` (Codex).
3. **Esquemas**: sin `$schema` para Claude; estrictos (`additionalProperties:false`, todo `required`) para Codex; en agy el veredicto se obtiene de la línea `ESTADO:`.
4. **`rate_limit_event` de Claude** permite gestionar el uso de forma proactiva (porcentaje de las ventanas de 5 h y 7 días, `resetsAt`).
5. **Riesgo 0.3 ampliado a Codex**: también carga las skills y memorias globales del usuario. La mitigación debe cubrir a Claude y a Codex.
6. **Errores de arranque de Codex** (`item.type=="error"` antes del primer turno) son advertencias de configuración.
7. **Fin de línea en worktrees**: definir `core.autocrlf` o `.gitattributes` por worktree en la Fase 3.

8. **Fijar siempre `--permission-mode`** en Claude (no heredar el modo global `auto`).
9. **Aprobaciones remotas de Claude** mediante `--permission-prompt-tool` + MCP con `structured_output=False`, siempre combinadas con `--disallowed-tools` (las lecturas se autoaprueban).
10. **`not_resumable`**: una sesión muerta antes del primer mensaje del modelo no se puede reanudar → reintentar el paso.
11. **Autenticación web**: el emparejamiento con cookie es obligatorio; las cabeceras de Tailscale no bastan (falsificables desde procesos locales).
12. **SDK MCP 2.x** (`MCPServer`).

## Defectos conocidos de los runners (aceptados; las POCs son desechables)

- POC-01: toma el último evento en lugar del evento `type=="result"` (falso negativo de C3).
- POC-02: C2 compara las rutas absolutas de `file_change` con las rutas relativas de `git diff`.
- POC-06: `--real claude` omite `--verbose` (la cancelación real se validó con un experimento equivalente).
- POC-05: no borra la rama del worktree.
- POC-07: C5 no compara `create_time` (posible falso positivo por reutilización o por el periodo de salida del proceso).
