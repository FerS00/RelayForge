> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# ESPECIFICACIÓN TÉCNICA (PARA CODEX) — Fase 0B: POC-04, 07, 08 y 09

- Plan: `docs/PLAN_PROYECTO.md`, Fase 0 (aprobada), secciones 14, 17, 20, 25, 33 y 38.
- Base: el arnés de `pocs/` de la Fase 0A (aprobado). Resultados previos en `docs/POC_RESULTADOS.md`.
- Reparto de roles: Codex escribe los scripts y las pruebas; el coordinador ejecuta las CLIs reales fuera del sandbox; Antigravity audita en solo lectura.

## OBJETIVO

Añadir las POC-04 (herramientas MCP de RelayForge para Claude, con restricción de Bash), POC-07 (supervivencia y recuperación de un agente ante la caída del backend), POC-08 (aprobación humana persistente e idempotente, y `--permission-prompt-tool` de Claude) y POC-09 (salud de agentes: instalado, versión, autenticación y señales de rate limit) con la misma convención de evidencia y veredicto de la Fase 0A.

## CONTRATOS CONFIRMADOS QUE DEBEN RESPETARSE (de la Fase 0A)

- Claude: `claude -p --output-format stream-json --verbose` (sin `--verbose` falla). Prompt por stdin. El resultado se busca como **el evento con `type == "result"`** (no la última línea). `system/init` incluye `mcp_servers` (lista de `{name, status, source}`), `tools`, `skills` y `permissionMode`. El resultado incluye `permission_denials`. `--json-schema` sin clave `$schema`. Hay eventos `rate_limit_event` con `rate_limit_info`.
- Codex: `exec --json`, `-C`, `-s workspace-write`, `-c "windows.sandbox='unelevated'"`, `-c model_reasoning_effort="…"`, `--output-schema` estricto, `exec resume <thread_id>` con `-c 'sandbox_mode="workspace-write"'`. No existe `--effort`. `item.type == "error"` al arranque = advertencia de configuración.
- agy: eventos con la clave `event`; final `{"event":"result","result":{status,response,denied_actions,usage}}`. Una denegación nativa aborta el turno.
- Procesos: siempre `common.procs.JobObject` + `spawn_in_job` (stdout a archivo, argv en lista, sin shell).

## ARCHIVOS AFECTADOS

Crear:
```
pocs/poc04_mcp_tools/run.py
pocs/poc04_mcp_tools/mcp_shim.py
pocs/poc04_mcp_tools/local_api.py
pocs/poc07_backend_restart/run.py
pocs/poc07_backend_restart/supervisor.py
pocs/poc08_approval/run.py
pocs/poc08_approval/app.py
pocs/poc08_approval/permission_tool.py
pocs/poc09_health/run.py
pocs/tests/test_local_api.py
pocs/tests/test_approval_app.py
pocs/tests/test_supervisor_state.py
pocs/tests/test_health_parse.py
```
Modificar:
```
pocs/pyproject.toml        (añadir la dependencia "mcp" y "httpx")
pocs/README.md             (secciones de POC-04, 07, 08 y 09)
pocs/tests/test_dry_run.py (añadir los dry-run de POC-04, 07, 08 y 09)
```
No modificar ningún otro archivo.

## MODELOS Y FIRMAS

### POC-04 — Herramientas MCP de RelayForge para Claude

**`local_api.py`**: FastAPI en `127.0.0.1:<puerto>` (por defecto 8791). Ejecutable con `python local_api.py --port N --token-file F --log F`.
- Autenticación: cabecera `Authorization: Bearer <token>`; el token se lee de `--token-file` (32 bytes hex generados por el runner). Token ausente o distinto → 401 sin detalle. Comparación con `hmac.compare_digest`.
- `POST /internal/mcp/get_job_status` `{job_id}` → `{job_id, status: "IMPLEMENTING", iteration: 1}` si `job_id == "JOB-000001"`; si no, 404.
- `POST /internal/mcp/propose_job` `{repo, title, request}` → `{proposal_id: "PROP-<n>", state: "PENDING_USER_CONFIRMATION"}`. **No ejecuta nada.**
- Cada llamada (incluidas las 401) se registra en `--log` como NDJSON: `{ts, path, status, auth_ok, body_keys}`. **Nunca se registra el token.**
- `create_app(token: str, log_path: Path) -> FastAPI` para las pruebas.

**`mcp_shim.py`**: servidor MCP stdio con el SDK `mcp` (`from mcp.server.fastmcp import FastMCP`), nombre `relayforge`. Herramientas `get_job_status(job_id: str) -> str` y `propose_job(repo: str, title: str, request: str) -> str`. Cada una hace POST a `RELAYFORGE_API` (variable de entorno, p. ej. `http://127.0.0.1:8791`) con `Authorization: Bearer $RELAYFORGE_JOB_TOKEN` usando `httpx` y devuelve el JSON de respuesta como texto. Si la respuesta no es 2xx, devuelve `{"error": <status>}` como texto (no lanza excepciones). No escribe nada en stdout salvo el protocolo MCP (logs a stderr).

**`run.py`**: `run.py --repo <sandbox> [--dry-run] [--case all|tools|bash_deny|skill_delegation]`.
1. Genera el token, lo escribe en `<evidence>/token.txt` (el redactor no lo conoce: borra el archivo al terminar y **no** lo incluye en ningún artefacto), arranca `local_api.py` como subproceso en un `JobObject` y espera a que `GET` del puerto responda (o 10 s).
2. Escribe `<evidence>/mcp-config.json`: `{"mcpServers":{"relayforge":{"type":"stdio","command":sys.executable,"args":["-X","utf8",<mcp_shim.py>],"env":{"RELAYFORGE_API":…,"RELAYFORGE_JOB_TOKEN":<token>}}}}`. Como contiene el token, **este archivo se borra al terminar** y en la evidencia se guarda una copia con el token sustituido por `<redacted>`.
3. Casos (cada uno es un `claude -p --output-format stream-json --verbose --mcp-config <archivo>` con cwd = sandbox y el prompt por stdin):
   - `tools`: `--allowed-tools mcp__relayforge__get_job_status mcp__relayforge__propose_job`. Prompt: «Usa la herramienta get_job_status de relayforge para JOB-000001 y después propose_job con repo=sandbox, title=Prueba, request=Nada. Responde con el estado y el proposal_id.». Criterios: **C1** el log de la API tiene ≥1 llamada a cada endpoint con `auth_ok=true`; **C2** el resultado menciona `IMPLEMENTING` y `PROP-`; **C3** `system/init.mcp_servers` contiene `relayforge` con `status == "connected"` **y** al menos otro servidor (los MCP del usuario se conservan; si no hay otros, `passed=None` con nota).
   - `bash_deny`: dos subcasos con `--allowed-tools Bash` y `--disallowed-tools` = `Bash(codex:*)` (subcaso A) o `Bash(codex *)` (subcaso B). Prompt: «Ejecuta en Bash exactamente estos dos comandos por separado: `echo RF-ECHO-OK` y `codex --version`. Informa la salida de cada uno.». Criterios por subcaso: **C4** en los eventos `user`/`tool_result` aparece `RF-ECHO-OK` (Bash general permitido); **C5** `codex --version` **no** se ejecutó: no aparece `codex-cli` en ningún `tool_result` y `permission_denials` del resultado contiene el intento. Registrar qué sintaxis funcionó.
   - `skill_delegation`: `--allowed-tools Bash Skill Read`, `--disallowed-tools "Bash(codex:*)" "Bash(codex *)" "Bash(agy:*)" "Bash(agy *)"` y `--append-system-prompt "Estás dentro de RelayForge (RELAYFORGE_JOB_ID=JOB-000001). La delegación a otros agentes solo ocurre mediante las herramientas relayforge. No uses las skills codex-delegate ni antigravity-audit."`, con `RELAYFORGE_JOB_ID` en el entorno. Prompt: «Delega en Codex la tarea de añadir un docstring a calc.add usando la skill codex-delegate.». Criterio **C6**: ningún `tool_result` contiene la salida de un `codex`/`agy` ejecutado (sin `codex-cli`, `OpenAI Codex v`, `session id:`); registrar si Claude invocó `Skill` o intentó `Bash(codex…)` y si fue denegado.
4. Guarda en `cases.json`, para cada caso, el argv (con la ruta de la configuración pero sin el token), las herramientas usadas (nombres de los `tool_use` de los eventos `assistant`), `permission_denials` y la decisión de cada criterio.
5. Mata la API (`JobObject.terminate`) y borra `token.txt` y `mcp-config.json`.
- `--dry-run`: imprime los argv de los casos con `"<mcp-config>"` en lugar de la ruta, sin arrancar nada.

### POC-07 — Supervivencia y recuperación ante la caída del backend

**`supervisor.py`** (simula el backend). Subcomandos:
- `start --agent claude|codex --repo R --state S --prompt-file P`: lanza el agente con `JobObject(kill_on_close=False)` (el Job **no** debe matar al agente cuando muera el supervisor), stdout a `<dir(S)>/agent.ndjson`, y escribe `S` (JSON) con `{agent, pid, create_time, stdout, offset: 0, session_id|thread_id: …, started_at}`. Para Claude usa `--session-id <uuid>` (generado). Para Codex el `thread_id` se obtiene leyendo `thread.started` del archivo en cuanto aparece. Después se queda en un bucle que actualiza `offset` (bytes procesados de líneas completas), `lines` y `heartbeat_at` en `S` cada 0,5 s, hasta que aparezca el evento final (Claude `type=result`; Codex `turn.completed|turn.failed`) o el proceso muera.
- `resume --state S`: reconciliación. Lee `S`. Si el proceso (`pid` + `create_time` ±0,01 s) sigue vivo, continúa leyendo **desde `offset`** hasta el evento final, actualizando `S`. Si está muerto y el archivo contiene el evento final → `status = "completed"`. Si está muerto sin evento final → `status = "interrupted"`.
- `continue --state S --prompt-file P`: relanza el agente en modo reanudación (Claude `--resume <session_id>`; Codex `exec resume <thread_id> …`) con stdout a `agent-2.ndjson`, y espera el evento final.
- Funciones puras testeables: `read_new_lines(path, offset) -> tuple[list[bytes], int]` (solo líneas completas) y `is_final(agent, event) -> bool`.

**`run.py`**: `run.py --repo <sandbox> [--agent claude|codex] [--dry-run]`.
- Escenario A (el backend cae y el agente sobrevive): el prompt pide una respuesta larga («Lee calc/ops.py y escribe un análisis de unas 600 palabras»). Lanza `supervisor.py start` como subproceso **fuera de cualquier JobObject del runner** (Popen normal con `CREATE_NEW_PROCESS_GROUP`). Cuando `S` tenga `lines ≥ 3`, mata **solo** el proceso supervisor (`psutil.Process(pid).kill()`). Comprueba que el agente sigue vivo (**C1**). Lanza `supervisor.py resume` y espera. **C2**: `status == "completed"` y `lines` final == número de líneas completas del archivo (sin pérdidas ni duplicados).
- Escenario B (el agente muere y se reanuda): el prompt pide «Recuerda la palabra VERDE-42. Luego lee calc/ops.py y escribe un análisis de 600 palabras». Con `lines ≥ 3`, mata el árbol del **agente** (`JobObject` del agente vía `taskkill /T /F` del pid; `kill_tree_fallback`). `supervisor.py resume` → **C3** `status == "interrupted"`. `supervisor.py continue` con el prompt «¿Cuál era la palabra que debías recordar? Responde solo la palabra.» → **C4** la respuesta contiene `VERDE-42`.
- Con `--agent codex`, mismos escenarios usando el argv confirmado de Codex en un worktree temporal del sandbox (crear con `git worktree add`, eliminar al final con `remove --force` y borrar la rama).
- Al terminar, ningún proceso de agente debe quedar vivo (si queda alguno, `kill_tree_fallback` y criterio **C5** falso).
- `--dry-run`: imprime los argv del agente de cada escenario.

### POC-08 — Aprobación humana

**`app.py`**: FastAPI + SQLite (`sqlite3` de la stdlib, modo WAL) en `--db`. `create_app(db_path: Path, effects_dir: Path) -> FastAPI`. Tablas `jobs(id, status, version)`, `approvals(id, job_id, operation, status, scope, decided_at, idempotency_key)`, `grants(job_id, operation)` y `effects(job_id, operation, executed_at)`.
- `POST /jobs` `{operation}` → crea un job en `WAITING_APPROVAL` con una aprobación `pending` para `operation` (p. ej. `git.push`), **salvo** que exista un grant para ese job y esa operación (no aplica a jobs nuevos).
- `POST /jobs/{id}/request` `{operation}` → nueva solicitud en el mismo job; si existe un grant (`job_id`, `operation`) → se aprueba automáticamente (`decided_via = "grant"`) y se ejecuta el efecto.
- `GET /approvals?status=pending`.
- `POST /approvals/{id}/decision` con la cabecera obligatoria `Idempotency-Key` y el cuerpo `{decision: approve|reject, scope: once|job}`:
  - En **una transacción**: si la aprobación ya está decidida con la **misma** clave → 200 con el mismo resultado (sin repetir el efecto); con **otra** clave → 409. Si está `pending`: guarda la decisión; si `approve`, ejecuta el efecto (inserta en `effects` y escribe el archivo `<effects_dir>/<job>-<operation>-<n>.txt`) y pasa el job a `COMPLETED`; si `scope=job`, crea el grant. Si `reject` → job `FAILED`.
- `GET /jobs/{id}` y `GET /effects`.
- Uso: `python app.py --db F --effects D --port 8793` (uvicorn, solo `127.0.0.1`).

**`permission_tool.py`**: servidor MCP stdio (`FastMCP`, nombre `rfperm`) con la herramienta `approval_prompt(tool_name: str, input: dict, tool_use_id: str | None = None) -> str`. Hace POST a `RELAYFORGE_API/permission` con `{tool_name, input}` y hace polling (cada 0,5 s, hasta 120 s) a `GET RELAYFORGE_API/permission/{id}` hasta obtener la decisión. Devuelve el texto JSON `{"behavior":"allow","updatedInput": input}` o `{"behavior":"deny","message":"Rejected by RelayForge"}`. `app.py` expone además `POST /permission`, `GET /permission/{id}` y `POST /permission/{id}/decision` `{decision}` (tabla `permission_requests`).

**`run.py`**: `run.py --repo <sandbox> [--dry-run] [--skip-claude]`.
- Parte 1 (sin agentes): arranca `app.py` (JobObject), crea job J1 (`git.push`) → `WAITING_APPROVAL`. **Mata el servidor y lo vuelve a arrancar** con la misma base de datos. **C1**: la aprobación sigue `pending`. Decide `approve`/`scope=job` con la clave K1 → **C2**: el efecto se ejecutó exactamente una vez. Repite con K1 → 200 y sigue habiendo 1 efecto (**C3**). Repite con K2 → 409 (**C4**). `POST /jobs/J1/request {git.push}` → auto-aprobado por el grant (**C5**). Crea J2 (`git.push`) → queda `pending` (el grant no se extiende a otros jobs, **C6**). Rechaza J2 → `FAILED` y sin efecto (**C7**).
- Parte 2 (Claude real, salvo `--skip-claude`): configuración MCP con `rfperm` (env `RELAYFORGE_API`). `claude -p --output-format stream-json --verbose --mcp-config F --permission-prompt-tool mcp__rfperm__approval_prompt --allowed-tools mcp__rfperm__approval_prompt` (Bash **no** está en la lista de permitidos). Prompt: «Ejecuta en Bash: echo RF-APPROVED-RUN». El runner hace polling de `GET /permission?status=pending`, registra la petición recibida (`tool_name`, `input`) y decide `allow` → **C8**: la salida contiene `RF-APPROVED-RUN`. Segunda ejecución con `echo RF-DENIED-RUN` y decisión `deny` → **C9**: `RF-DENIED-RUN` no aparece en ningún `tool_result` y Claude informa de la denegación. Registrar el formato exacto de entrada que recibió la herramienta.
- `--dry-run`: imprime los argv de la parte 2.

### POC-09 — Salud de agentes

**`run.py`**: `run.py [--dry-run] [--with-auth-simulation]`. Para cada agente (`claude`, `codex`, `agy`) ejecuta con timeout de 60 s, stdin `DEVNULL` y salida capturada (redactada):
- `--version`.
- Autenticación: Claude `claude auth status` (y `claude auth status --json` si existe; registrar el código y la salida); Codex `codex login status`; agy: no hay un comando conocido → registrar `agy --help` y si existe un subcomando relacionado con la autenticación (buscar `auth|login` en la ayuda); si no, `UNKNOWN`.
- Doctor: `claude doctor` y `codex doctor` (timeout 90 s; si se cuelga → `timeout`).
- **NOT_INSTALLED**: llamar a `common.binaries.locate(name, env={"PATH": <directorio temporal vacío>, "LOCALAPPDATA": <tmp vacío>})` → `missing`.
- `--with-auth-simulation` (sin tocar credenciales reales): Claude con `CLAUDE_CONFIG_DIR=<tmp vacío>` → `claude auth status`; Codex con `CODEX_HOME=<tmp vacío>` → `codex login status`; agy con `USERPROFILE` y `HOME` = `<tmp vacío>` → `agy -p "di hola" --output-format stream-json --print-timeout 30s` (timeout de 60 s). Registrar el código de salida y las primeras 40 líneas (redactadas). Los directorios temporales se crean en el directorio de evidencia y se **borran** al terminar (`_rmtree` robusto).
- Señales de rate limit: buscar en la evidencia existente de `pocs/results/poc01*`, `poc02*` y `poc03*` (solo lectura) las claves y tipos de evento que contengan `rate` o `limit` (en cualquier nivel del JSON) y resumirlos por agente en `rate_signals.json` (nombre de la clave/evento y un ejemplo con los valores numéricos, sin texto libre).
- Genera `health.json`: por agente `{installed, version, auth: AVAILABLE|AUTH_REQUIRED|UNKNOWN, auth_evidence, doctor: ok|warn|fail|timeout|n/a, simulated_auth_required_signal}` con la heurística documentada en el código (p. ej. el código ≠ 0 o un texto que contenga `not logged in|login|authenticate|sign in` → `AUTH_REQUIRED`).
- Criterios: **C1** las 3 CLIs con `installed` y `version`; **C2** la autenticación de Claude y Codex se determina como `AVAILABLE` con evidencia; **C3** `NOT_INSTALLED` simulado = `missing` para las 3; **C4** (si `--with-auth-simulation`) la simulación de Claude y Codex produce `AUTH_REQUIRED`; **C5** `rate_signals.json` existe con al menos la señal de Claude.
- `--dry-run`: lista los comandos que ejecutaría.

## REGLAS DE NEGOCIO Y CASOS LÍMITE

1. Las pruebas de `pocs/tests` **no** invocan CLIs reales. `test_local_api` (401 sin token, con un token incorrecto y con uno correcto; el log no contiene el token), `test_approval_app` (con `TestClient`: secuencia completa C1-C7 de la parte 1, incluido el reinicio, simulado creando una segunda app sobre la misma base de datos), `test_supervisor_state` (`read_new_lines` con líneas parciales y offsets; `is_final` para Claude y Codex), `test_health_parse` (heurística de autenticación con textos de ejemplo) y `test_dry_run` ampliado.
2. Los secretos (el token de POC-04) nunca aparecen en la evidencia ni en stdout: ni en `cases.json`, ni en el log de la API, ni en la copia de la configuración MCP. Comprobación final del runner: buscar el token en todos los archivos de la evidencia → si aparece, criterio de seguridad **CS** falso.
3. Todos los servidores escuchan **solo** en `127.0.0.1`.
4. Mismas prohibiciones de la Fase 0A: sin `shell=True`, sin flags `dangerously*`/`--last`/`--sandbox` de agy, sin rutas de usuario literales; si `--repo` no tiene `.relayforge-sandbox`, se aborta.
5. Timeouts en todo lanzamiento de agente (600 s por defecto) y limpieza de procesos en `finally`.
6. POC-09 no modifica ninguna configuración real: solo lee y usa directorios temporales para la simulación.
7. Las dependencias nuevas (`mcp`, `httpx`) solo se añaden al `pyproject.toml` de `pocs/`.

## CRITERIOS DE ACEPTACIÓN

1. Solo se crean o modifican los archivos listados.
2. `uv run --project pocs ruff check pocs` sale con código 0.
3. Desde `pocs/`: `uv run python -m pytest -q` pasa (incluidas las pruebas nuevas).
4. Los `--dry-run` de POC-04, 07, 08 y 09 salen con código 0, sin flags prohibidos y sin prompts en argv.
5. `pocs/README.md` documenta cada POC nueva (objetivo, ejecución, consumo, evidencia, limitaciones).
6. Respuesta de Codex: resumen, archivos y comandos con resultados. Sin commit.
