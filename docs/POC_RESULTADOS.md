> Material histórico de POCs/validaciones previas. Contrasta procedimientos y resultados con el [plan vigente](PLAN_PROYECTO.md) y las guías actuales de instalación/Docker. No acredita aceptación del despliegue nuevo.

# Resultados de las POCs — Fase 0

- Plan: `docs/PLAN_PROYECTO.md` (Fase 0). Especificación: `docs/specs/FASE_0A.md` (con las adendas 1 y 2).
- Fecha: 2026-10-02. Máquina: PC principal, Windows 11 (10.0.26300), Python 3.13.15 (venv de `pocs/`), Git 2.51.0.
- Versiones de agentes: Claude Code 2.1.283, codex-cli 0.159.2, agy 1.2.15.
- La evidencia cruda (redactada) está en `pocs/results/<poc>/<timestamp>/`, ignorado por Git. Se cita aquí el directorio de cada ejecución relevante.
- Ejecutó: el coordinador (Claude), fuera del sandbox, salvo cuando se indica otra cosa.
- Actualización 2026-10-03: se registran los resultados de la laptop (POC-10 y POC-11) y el cierre de la Fase 0. Los datos de la laptop proceden de la verificación de Codex y de observaciones del usuario, como se indica en cada sección.
- Nota sobre la evidencia cruda: a 2026-10-03 el árbol de trabajo de la PC principal solo conserva `pocs/results/poc03_antigravity_audit/` y `pocs/results/poc05_worktree/`; el resto de los directorios citados en este documento no está disponible en ese árbol (el directorio está ignorado por Git).

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
| POC-10 Arranque automático | **PARCIAL**. Línea base interactiva en la PC: PASS. En la laptop, los tres modos produjeron evidencia etiquetada; las tres CLIs figuran `AVAILABLE` y sus sondas profundas terminaron con código 0 y resultado no vacío; `git ls-remote --heads` terminó en código 0 (lectura no interactiva, no escritura). Falta validar `push` según 38.2 y reconciliar la discrepancia temporal. Las tareas ya se retiraron y se comprobó que no quedan registradas | Fase 4 (y Fase 7 para el push) |
| POC-11 Tailscale serve | **PARCIAL**. Parte local en la PC: PASS (riesgo de falsificación confirmado). Laptop + móvil: `/whoami` y SSE de 600 s observados por el usuario; falsificación desde otro dispositivo no probada; HTTP 502 tras reiniciar porque `app.py` no arranca sola | Fase 4, autenticación |

**Cierre de la Fase 0 (2026-10-03):** sus criterios de aceptación explícitos (POC-01, 02, 03, 05, 06 y 07 en PASS o con alternativa documentada, y el plan actualizado) se cumplen. POC-10 y POC-11 no forman parte de esos criterios y quedan parciales; R-1, R-2 y R-4 siguen abiertas, mientras que R-3 (limpieza) y R-5 (estado de las CLIs) están cerradas en `docs/PLAN_PROYECTO.md` (Fase 0, «Cierre de la Fase 0»).

## POC-01 — Claude Code stream-json

Evidencia: `pocs/results/poc01_claude_stream/20261002-215900/`, `…/20261002-220126*` y la última ejecución, además de un experimento manual con `--json-schema`.

| Supuesto | Resultado | Estado |
|---|---|---|
| `-p --output-format stream-json` requiere `--verbose` | Sin él: `Error: When using --print, --output-format=stream-json requires --verbose` | **CONFIRMED** |
| Eventos incrementales | Primera línea en ~1,4-1,5 s; 24-25 eventos antes del resultado | **CONFIRMED** |
| Texto del asistente en streaming | Sin `--include-partial-messages` llega por mensaje completo (6-25 s). Con la opción, llega en fragmentos: ver POC-01b | **CONFIRMED** (POC-01b) |
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
- POC-01b (2026-10-03) confirmó la entrega de fragmentos; ver su sección. La evidencia cruda de POC-01 no está en el árbol de trabajo actual (ver la nota de la cabecera), así que los fixtures de la Fase 1 deben recuperarse o recapturarse.

## POC-01b — Fragmentos con `--include-partial-messages`

Fecha: 2026-10-03. Claude Code 2.1.283, PC principal, repositorio de pruebas. Ejecutó: el coordinador (Claude). Capturas saneadas en `pocs/results/poc01b/claude-2.1.283/` (ignorado por Git). **Veredicto: PASS.**

| Supuesto | Resultado | Estado |
|---|---|---|
| `--include-partial-messages` entrega fragmentos | Líneas `type=stream_event`; texto en `event.delta.text` cuando `event.type=content_block_delta` y `event.delta.type=text_delta` (85 fragmentos en un turno de ~150 palabras) | **CONFIRMED** |
| Latencia | Primer fragmento a 12,8 s; `assistant` completo a 16,7 s: los fragmentos adelantan ~4 s | **CONFIRMED** |
| El mensaje final repite los fragmentos | La concatenación de los `text_delta` es idéntica al texto del `assistant` → el `assistant` sustituye al acumulado | **CONFIRMED** |
| Llega razonamiento en los fragmentos | Sí: `content_block_start` `thinking`, `thinking_delta`, `signature_delta`; también `input_json_delta` de herramientas → se descartan | **CONFIRMED** |
| Reanudación con fragmentos | `--resume` respondió con la palabra clave del turno anterior, también en fragmentos | **CONFIRMED** |
| Campo `parent_tool_use_id` | Presente en cada `stream_event` (nulo en el agente principal) → filtrar los no nulos (subagentes) | **CONFIRMED** (filtro de diseño) |

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

### Ronda 1 — reintentos individuales tras el primer reinicio (≈02:38–02:41, 2026-10-03)

- Tras el reinicio del 2026-10-03, las tres tareas (`Logon`/Interactive, `StartupS4U`/S4U y `StartupPassword`/Password) informaron `LastTaskResult=0`. Las sondas separadas confirmaron Claude, Codex y agy `AVAILABLE`; las sondas profundas de cada CLI terminaron con código 0 y resultado no vacío.
- Evidencia atribuible por modo: `20261003-023821.json` (StartupS4U, sesión 0), `20261003-023859.json` (StartupPassword, sesión 0) y `20261003-024116.json` (Logon, sesión 1). Estos son reintentos individuales después del reinicio. En el arranque simultáneo solo quedaron dos JSON para tres tareas porque el nombre tenía precisión de un segundo y podía sobrescribir; esos dos archivos no se atribuyen con certeza a un modo.
- Git: `git ls-remote --heads` contra el remoto público de RelayForge terminó con código 0, pero la consulta es anónima y no demuestra que GCM tenga credenciales en las tareas. **El `push` del criterio 38.2 no se ejecutó**: no existe un remoto privado de pruebas configurado y la especificación Fase 0C define la comprobación de Git como solo lectura. POC-10 queda parcial respecto al criterio de Git/push.
- Corrección aplicada al runner: los próximos JSON incorporan modo, PID y marcas de tiempo, se crean en modo exclusivo y no sobrescriben evidencia previa. Las tareas actuales no llevan `--label`; deben volver a registrarse para probar el cambio. Revalidado en la ronda 2: tres tareas simultáneas produjeron tres archivos distintos con modo y PID en el nombre.

### Ronda 2 — arranque automático simultáneo con tareas etiquetadas (2026-10-03, ≈10:08–10:10, UTC−05:00)

- Fuente: verificación de Codex (lectura de los tres JSON y de `LastTaskResult`) entregada al coordinador. Los JSON no están en el repositorio ni se reproducen completos aquí; llegaron a la PC principal por Taildrop. En este cierre Claude no volvió a leer los archivos: solo se registran los campos que Codex verificó.
- `boot_time` común a los tres JSON: `2026-10-03T15:08:32.357811+00:00` (= 10:08:32.357811 -05:00).

| Modo (tarea `RelayForge-POC10-<modo>`) | Archivo de evidencia | `started_at` (-05:00) | Desfase desde `boot_time` | `LastTaskResult` | Contexto Windows | Sondas CLI | `git_remote` (`git ls-remote --heads`, solo lectura) |
|---|---|---|---|---|---|---|---|
| StartupPassword | `20261003-100945-StartupPassword-10084.json` | 10:09:45.545325 | 73 s | 0 | sesión 0; uptime 18 s | tres `AVAILABLE`; deep: código 0 y resultado no vacío | `returncode=0`, `timed_out=false`, `credentials_error=false` |
| StartupS4U | `20261003-100946-StartupS4U-10092.json` | 10:09:46.744234 | 74 s | 0 | sesión 0; uptime 18 s | tres `AVAILABLE`; deep: código 0 y resultado no vacío | igual |
| Logon | `20261003-100947-Logon-12248.json` | 10:09:47.214165 | 75 s | 0 | sesión 1; uptime 18 s | tres `AVAILABLE`; deep: código 0 y resultado no vacío | igual |

Los tres `started_at` caen dentro de una ventana de 1,67 s.

Qué muestra:

1. **Atribución resuelta.** Tres tareas simultáneas produjeron tres archivos distintos, con modo y PID en el nombre. Queda revalidada la corrección del runner (etiqueta, PID y creación exclusiva) y desaparece la ambigüedad de la ronda 1.
2. **Las tres CLIs están verificadas en los tres JSON.** En cada modo, Claude, Codex y agy figuran `AVAILABLE`; cada sonda profunda terminó con código 0 y resultado no vacío. `LastTaskResult=0` por sí solo solo probaría que terminó el script; aquí la conclusión también se apoya en esos campos de cada JSON.
3. **Git: lectura autenticada, no escritura.** `git ls-remote --heads` (con `GIT_TERMINAL_PROMPT=0` y `GCM_INTERACTIVE=never`) terminó en código 0, sin tiempo agotado ni error de credenciales, en los tres modos, contra un remoto privado de la cuenta del propietario; su nombre no se registra aquí porque el repositorio de RelayForge es público. *Inferencia:* leer un remoto privado sin interacción indica que había credenciales utilizables de forma no interactiva; la evidencia no identifica qué proveedor de credenciales respondió ni demuestra permiso de escritura. **No se ejecutó `git push`**: la especificación de la Fase 0C define el chequeo como solo lectura y esa discrepancia con el criterio de 38.2 no se modifica en este cierre.

Sobre los tiempos:

- `started_at` (y la marca del nombre del archivo) se captura **después** de ejecutar las sondas (en `main()` de `probe.py`, `run_probe` va antes que `started_at`). Es la hora de finalización de la sonda, no la de inicio de la tarea: los desfases de 73 a 75 s son de finalización. Los tres JSON registran `context.uptime_seconds=18`; registran `session_id=0` para `StartupPassword` y `StartupS4U`, y `session_id=1` para `Logon`. Esto confirma en qué sesión de Windows corría cada proceso al capturar el contexto, pero no demuestra por sí solo que no hubiera una sesión interactiva abierta.
- **Discrepancia registrada, sin resolver.** El usuario reporta unos tres minutos en la pantalla de bloqueo antes de iniciar sesión. La marca de finalización del JSON de `Logon` está 75 s tras `boot_time`, solo 1,67 s después de `StartupPassword`; además, `Get-ScheduledTaskInfo` mostró `LastRunTime=10:08:08` en las tres tareas, mientras que los JSON terminaron entre 10:09:45 y 10:09:47. Los `session_id` (0/0/1) y `uptime_seconds` (18/18/18) sí se verificaron, pero no reconcilian por sí solos esos tiempos con la secuencia reportada. No se asigna una causa.
- Efecto sobre las conclusiones: **no se afirma** que las tareas de inicio se ejecutaran antes de cualquier sesión interactiva ni que el JSON de `Logon` corresponda al inicio de sesión manual. Se mantiene la evidencia verificada de los tres JSON, sus sondas y `git_remote`.
- Para reconciliar, si hace falta para elegir el modo de servicio, contrastar los eventos del Programador de tareas, arranque e inicio de sesión de Windows entre las 10:08 y 10:12. Esa consulta no se ejecutó en este cierre.

Limpieza administrativa completada: tras la confirmación del usuario, `Get-ScheduledTask -TaskName 'RelayForge-POC10-*'` no devolvió tareas.

**Veredicto POC-10: PARCIAL.**

- Establecido: las tres CLIs responden bajo tarea programada en los modos `Logon`, `StartupS4U` y `StartupPassword` (ronda 1); el runner atribuye la evidencia por modo (ronda 2); hay lectura Git no interactiva de un remoto privado en los tres modos.
- No establecido: escritura remota con Git Credential Manager (`git push`, criterio de 38.2) y ejecución de los disparadores de inicio antes de cualquier sesión interactiva (discrepancia temporal sin resolver).
- Decisiones asociadas: D-09 (inicio de sesión automático) sigue pendiente; D-11 (validar `git push`) es nueva.

## POC-11 — Tailscale serve (parte ejecutada)

- El usuario verificó `/whoami` desde el celular y observó el SSE durante 600 segundos. Esto completa la prueba móvil solicitada; el log local disponible no conserva un registro de esos 600 segundos.
- `tailscale serve status` confirma la ruta tailnet-only hacia `127.0.0.1:8792`. Después del reinicio, la app no estaba escuchando y `/whoami` devolvió HTTP 502. La configuración de Serve persiste, pero `app.py` no se inicia automáticamente y debe arrancarse manualmente.
- La comprobación local registra `identity_absent_direct=true` y `spoof_accepted_direct=true`: cualquier proceso local puede falsificar las cabeceras. La identidad de Tailscale debe complementarse con cookie de emparejamiento y CSRF; nunca usar las cabeceras como único control. No se observó uso de Funnel.
- Veredicto: **PARCIAL.** `/whoami` y SSE móvil comprobados por observación del usuario; no se probó falsificación desde otro dispositivo. La falsificación local está confirmada, por lo que el emparejamiento y CSRF siguen siendo obligatorios. La disponibilidad tras reinicio depende del arranque manual de la app.

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
13. **Medir el desfase de arranque con `context.uptime_seconds`**, no con `started_at` ni con la marca del nombre del archivo (se capturan al terminar la sonda).
14. **`ls-remote` solo prueba lectura.** Validar Git en sesión no interactiva exige una prueba de escritura (`git push` a un remoto de pruebas autorizado): D-11 del plan.

## Defectos conocidos de los runners (aceptados; las POCs son desechables)

- POC-01: toma el último evento en lugar del evento `type=="result"` (falso negativo de C3).
- POC-02: C2 compara las rutas absolutas de `file_change` con las rutas relativas de `git diff`.
- POC-06: `--real claude` omite `--verbose` (la cancelación real se validó con un experimento equivalente).
- POC-05: no borra la rama del worktree.
- POC-07: C5 no compara `create_time` (posible falso positivo por reutilización o por el periodo de salida del proceso).
- POC-10: `started_at` y la marca del nombre del archivo se capturan tras ejecutar las sondas (hora de finalización, no de inicio); el desfase de inicio está en `context.uptime_seconds`. La sonda sale con código 0 incluso si una CLI falla, así que `LastTaskResult=0` no implica `AVAILABLE`.
