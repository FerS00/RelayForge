> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# ESPECIFICACIÓN TÉCNICA (PARA CODEX) — Fase 1: web → backend → Claude → streaming → respuesta

- Estado: **Aprobada** (2026-10-03; Fase 1 aprobada en bloque, D-12; conflictos resueltos, D-16). Auditoría de Antigravity: APROBADO CON OBSERVACIONES (2026-10-03), observaciones incorporadas. POC-01b ejecutada: PASS (sección 3).
- Plan: `docs/PLAN_PROYECTO.md`, sección 36, Fase 1. Esta versión se alinea con las secciones 12, 13, 23, 24, 27, 28, 29, 30, 31, 35 y 36 del plan (detalle en la sección 10). El alcance y los criterios de aceptación de la fase no cambian.
- Evidencia: `docs/POC_RESULTADOS.md`: POC-01 (PASS), POC-04 y POC-08 (restricciones de Claude y permisos), POC-09 (autenticación).
- Dependencia: Fase 0 completada (2026-10-03). POC-10 y POC-11 quedan parciales (R-1, R-2 y R-4 abiertas). No bloquean esta fase, pero sí las fases 4 y 7.
- Precondiciones de implementación: cumplidas. POC-01b en PASS y capturas reales saneadas disponibles para las fixtures (regla 13).
- Revisión de Antigravity sobre esta versión: APROBADO CON OBSERVACIONES (2026-10-03). Hallazgos: POC-01b pendiente (resuelto: ejecutada), ambigüedad `step`/`step_id` (resuelta en 6.9) y `workspace_dir` en lugar de `repo_id` (aceptado hasta la Fase 3).
- Etiquetas: [PLAN §n] lo fija el plan; [POC-nn] lo fija la evidencia; [PROPUESTA] decisión de esta especificación que el plan no fija; [DECISIÓN D-16] lo decidió el usuario. Tras la aprobación todo es vinculante; las etiquetas solo sirven para la revisión.

## 1. OBJETIVO

[PLAN §36] Primer valor visible: enviar un mensaje desde el navegador (local) y ver la respuesta de Claude Code real en streaming. Entregable: `relayforge serve` → `http://127.0.0.1:8787` → chat con Claude en el directorio de trabajo configurado, con la respuesta en streaming y la sesión reanudada en el siguiente mensaje.

Terminología: un **turno** es un step de tipo `chat` [PLAN §12, `job_steps.kind`]. En esta fase no hay Jobs; el `step_id` del turno es un ULID.

## 2. FUERA DE ALCANCE

No crear código, tablas, rutas ni ajustes para: Jobs y máquina de estados (Fase 2); repositorios registrados, worktrees, Codex y diff (Fase 3); acceso remoto, Tailscale, emparejamiento, CSRF y despliegue en la laptop (Fase 4); checks/tests de proyectos (Fase 5); Antigravity, triage y bucle de revisión (Fase 6); políticas, aprobaciones y entrega (Fase 7); cancelación por el usuario, timeouts, rate limits y reconciliación (Fase 8); workflows y métricas (Fase 9); endurecimiento e instalación open-source (Fase 10); diseño visual, UX móvil avanzada y PWA (Fase 11).

Tampoco: `--json-schema`, `--permission-prompt-tool`, servidor MCP de RelayForge, `doctor` y estado de agentes, clasificación de errores de autenticación o de rate limit, replay de eventos por `Last-Event-ID` (Fase 2, criterio 4), y plataformas distintas de Windows.

La Fase 1 no tiene autenticación: no se expone fuera de `127.0.0.1`, ni con `tailscale serve`, hasta la Fase 4.

## 3. DECISIÓN DE STREAMING Y POC-01b

[PLAN §23] Los fragmentos de texto del agente (`agent.message.delta`) se emiten en vivo. Se persisten consolidados: un `agent.message` por mensaje completo, más deltas coalescidos cada ~500 ms.

**POC-01b — PASS (2026-10-03, Claude Code 2.1.283, ejecutada por el coordinador).** Comando: `claude -p --output-format stream-json --verbose --include-partial-messages --session-id <uuid> --permission-mode default --disallowed-tools …`, prompt por stdin, en el repositorio de pruebas; segundo turno con `--resume`.

- **(a) Forma de los fragmentos:** líneas `{"type": "stream_event", "event": {...}, "session_id", "parent_tool_use_id", "uuid"}`. El texto llega en `event.type == "content_block_delta"` con `event.delta.type == "text_delta"` y `event.delta.text`. Además aparecen `message_start`, `content_block_start` (`text`, `thinking`, `tool_use`), `content_block_stop`, `message_delta` y `message_stop`, y deltas `thinking_delta`, `signature_delta` e `input_json_delta`.
- **(b) Latencia:** primer `text_delta` a 12,8 s del inicio; el `assistant` completo con ese texto llegó a 16,7 s. Los fragmentos adelantan la respuesta unos 4 s en un turno de ~150 palabras (85 fragmentos).
- **(c) Duplicación:** la concatenación de los `text_delta` es **idéntica** al texto de los bloques `text` del `assistant` posterior. El `assistant` repite el texto; no debe añadirse por segunda vez.
- **(d) Razonamiento:** sí llega: `content_block_start` de tipo `thinking`, `thinking_delta` y `signature_delta`. Se descartan.
- **(e) Capturas:** saneadas en `pocs/results/poc01b/claude-2.1.283/text_turn.ndjson` (158 eventos) y `resume_turn.ndjson` (12 eventos). Sin rutas personales, listas de skills, servidores MCP ni hooks; razonamiento y salidas de herramientas sustituidos por `[REDACTADO-…]`; `session_id` sustituido por un UUID fijo; `system/init` recortado. Ese directorio está ignorado por Git: Codex las copia a `tests/fixtures/claude/2.1.283/`.
- **Reanudación:** el segundo turno con `--resume` respondió con la palabra clave del primero, también en fragmentos.
- **Varios mensajes por turno:** un turno con herramientas emite varios `message_start`/`message_stop`; cada mensaje del asistente tiene sus propios fragmentos.

Reglas que fija POC-01b (aplicadas en 6.5.2):
- Solo cuentan los `stream_event` con `event.delta.type == "text_delta"` y `parent_tool_use_id` nulo. Todo otro `stream_event` se descarta.
- Los fragmentos se acumulan por mensaje (desde `message_start` hasta `message_stop`). Al llegar el `assistant` del mensaje, su texto **sustituye** al acumulado: se emite `agent.message` con el texto completo y el acumulado se descarta. Nunca se suman fragmentos y mensaje.
- `--include-partial-messages` se añade siempre al argv (6.5.1).

## 4. DECISIONES DEL USUARIO (D-16, 2026-10-03)

- **C-1 · Ruta y ámbito del SSE:** un stream por conversación, `GET /api/stream?conversation={id}`, con `seq` por conversación. El plan unifica la notación en sus secciones 23 y 28: `?conversation={id}`, `?job={id}` y `?scope=global`.
- **C-2 · Bind:** sin ajuste de host en la Fase 1; el host es la constante `127.0.0.1`. `RELAYFORGE_BIND` llega en la Fase 4 o la 10, con la guardia de T10.
- **C-3 · Formato:** texto plano con `white-space: pre-wrap`. Markdown se reevalúa en la Fase 11.
- **Interfaz (D-15):** la web es una interfaz de agente de IA centrada en la conversación (6.10). En esta fase la barra lateral lista conversaciones; los repositorios y las tareas simultáneas (D-13, D-14) llegan en las Fases 2 y 3 sobre la misma estructura.

## 5. ARCHIVOS AFECTADOS

Crear (rutas exactas; no se añade ningún otro archivo sin una especificación nueva):

```
pyproject.toml
uv.lock
LICENSE
.env.example
CLAUDE.md
docs/ESTADO_TRABAJO.md
src/relayforge/__init__.py
src/relayforge/__main__.py
src/relayforge/cli.py
src/relayforge/settings.py
src/relayforge/core/__init__.py
src/relayforge/core/events.py
src/relayforge/core/chat.py
src/relayforge/core/ids.py
src/relayforge/adapters/__init__.py
src/relayforge/adapters/base.py
src/relayforge/adapters/claude/__init__.py
src/relayforge/adapters/claude/adapter.py
src/relayforge/adapters/claude/parser.py
src/relayforge/adapters/claude/orchestrator.py
src/relayforge/process/__init__.py
src/relayforge/process/supervisor.py
src/relayforge/platform/__init__.py
src/relayforge/platform/windows.py
src/relayforge/db/__init__.py
src/relayforge/db/models.py
src/relayforge/db/session.py
src/relayforge/db/migrations/env.py
src/relayforge/db/migrations/script.py.mako
src/relayforge/db/migrations/versions/0001_initial.py
src/relayforge/api/__init__.py
src/relayforge/api/app.py
src/relayforge/api/schemas.py
src/relayforge/api/sse.py
src/relayforge/api/routes/__init__.py
src/relayforge/api/routes/conversations.py
src/relayforge/api/routes/stream.py
tests/conftest.py
tests/fakes/fake_agent.py
tests/fixtures/claude/2.1.283/text_turn.ndjson
tests/fixtures/claude/2.1.283/resume_turn.ndjson
tests/unit/test_claude_parser.py
tests/unit/test_claude_adapter.py
tests/unit/test_settings.py
tests/unit/test_supervisor.py
tests/unit/test_cli.py
tests/unit/test_ids.py
tests/integration/test_chat_flow.py
tests/integration/test_stream_sse.py
tests/integration/test_db_migrations.py
tests/integration/test_http_security.py
web/package.json
web/package-lock.json
web/index.html
web/vite.config.ts
web/tsconfig.json
web/tsconfig.node.json
web/eslint.config.js
web/src/vite-env.d.ts
web/src/main.tsx
web/src/App.tsx
web/src/api.ts
web/src/lib/eventStream.ts
web/src/lib/eventStream.test.ts
web/src/components/ConversationList.tsx
web/src/components/ChatView.tsx
web/src/components/ChatView.test.tsx
web/src/styles.module.css
```

Modificar:
- `.gitignore`: solo añadir lo que falte (p. ej. `.mypy_cache/`, `*.egg-info/`). Ya cubre `.env`, `*.db*`, `.venv/`, `data/`, `logs/`, `node_modules/` y `dist/`.
- `AGENTS.md`: se conserva íntegro; solo se permite añadir al final una sección «Desarrollo» con los comandos reales de instalación, pruebas, lint y arranque, una vez verificados.

No tocar: `pocs/**` (incluidos `pocs/pyproject.toml` y `pocs/uv.lock`), `docs/PLAN_PROYECTO.md`, `docs/POC_RESULTADOS.md`, `docs/specs/**` y `README.md`.

## 6. MODELOS Y FIRMAS

### 6.1 Proyecto y herramientas

- `pyproject.toml` [PLAN §30, §36]: paquete `relayforge` 0.1.0, licencia Apache-2.0, diseño `src/`, script de consola `relayforge = relayforge.cli:main`. `requires-python >= 3.13` [PROPUESTA: el venv de `pocs/` usa 3.13.15].
- Dependencias de ejecución [PROPUESTA]: `fastapi`, `uvicorn`, `sqlalchemy` 2.x, `alembic`, `pydantic-settings` y `pyyaml` (para `settings.yaml`, §31). Desarrollo: `pytest`, `httpx`, `psutil`, `ruff`, `mypy` y `types-PyYAML`. Cada dependencia se justifica en `docs/ESTADO_TRABAJO.md`. Los ULID no necesitan dependencia (6.4).
- Herramientas [PLAN §35]: `ruff`, `mypy` y `pytest` se configuran en el `pyproject.toml` raíz. Excluyen `pocs/`. `pytest` recoge solo `tests/`. No hay workspace de uv: `pocs/` sigue siendo un proyecto independiente.
- `web/` [PLAN §29, §30, §32]: `package.json` con los scripts `build` (`vite build`), `lint` (`eslint .`), `typecheck` (`tsc --noEmit`) y `test` (`vitest run`). Gestor: npm, con `package-lock.json`. La versión de Node.js la fija la versión de Vite instalada; Codex la verifica en la documentación oficial y la registra en `docs/ESTADO_TRABAJO.md`.
- `LICENSE`: texto oficial de Apache-2.0 sin modificar [PLAN §30].
- `CLAUDE.md`: breve; remite a `AGENTS.md`, `docs/PLAN_PROYECTO.md` y `docs/ESTADO_TRABAJO.md` sin repetir reglas [PLAN §30].
- `docs/ESTADO_TRABAJO.md`: checkpoint verificado al terminar. Incluye el estado de cada criterio con el comando ejecutado y su resultado, y los pendientes (incluido POC-01b). No contiene rutas personales ni secretos.

### 6.2 Configuración [PLAN §31]

| Ajuste | Variable de entorno | Obligatorio | Por defecto | Regla |
|---|---|---|---|---|
| `workspace_dir` | `RELAYFORGE_WORKSPACE_DIR` [PROPUESTA] | sí | — | Directorio existente. Es el `cwd` de Claude en las conversaciones nuevas. |
| `port` | `RELAYFORGE_PORT` [PLAN §31] | no | `8787` [PLAN §36] | Entero entre 1024 y 65535. El flag `--port` tiene prioridad. |
| `home` | `RELAYFORGE_HOME` [PLAN §31] | no | `%LOCALAPPDATA%\RelayForge` [PLAN §31] | Directorio de datos. Se crea si falta. Se resuelve primero porque localiza `config/settings.yaml`. |
| `claude_executable` | `RELAYFORGE_CLAUDE_BIN` [PLAN §31] | no | `claude` en PATH | Si no se resuelve, `relayforge serve` sale con código 2. |
| `claude_model` | `RELAYFORGE_CLAUDE_MODEL` [PROPUESTA: análoga a `RELAYFORGE_CODEX_MODEL` de §31] | no | vacío | Si no está vacío, se pasa como `--model`. |

- **Precedencia** [PLAN §31]: (1) valores por defecto del código; (2) `<home>/config/settings.yaml`, opcional, con las claves de la tabla en minúsculas (la aplicación no lo crea); (3) variables `RELAYFORGE_*` del proceso; (4) flags de CLI. `home` solo puede venir de la variable o del valor por defecto.
- **`.env`** [PROPUESTA]: la aplicación no lee ningún fichero `.env` en la Fase 1. La precedencia de §31 no lo incluye, y no depender del directorio de trabajo evita comportamientos distintos según desde dónde se lance. `.env.example` documenta las variables.
- `load_settings(**overrides) -> Settings`: lanza `SettingsError` con un mensaje sin valores sensibles.
- El host no es un ajuste: es la constante `127.0.0.1` (D-16, C-2).
- `.env.example` [PROPUESTA]: solo las variables de esta fase, con el comentario «cárgalas en el entorno; los demás ajustes de la sección 31 se añaden en sus fases».

### 6.3 Base de datos [PLAN §12, §24]

SQLite en `<home>/relayforge.db`, con `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON` y un solo escritor en el proceso [PLAN §24]. SQLAlchemy 2 y Alembic [PLAN §12]. Las marcas de tiempo son texto ISO-8601 UTC [PLAN §12]. La migración `0001_initial` crea solo estas tres tablas, con los nombres y campos del plan (sin `job_id` ni tablas de Jobs).

- `conversations`: `id` TEXT (ULID, PK) · `title` TEXT [PROPUESTA: por defecto «Nueva conversación»; tras el primer mensaje, sus primeros 60 caracteres con espacios colapsados] · `workspace_dir` TEXT, ruta absoluta fijada al crear [PROPUESTA: sustituye a `repo_id` hasta la Fase 3] · `orchestrator` TEXT = `claude` [PLAN §12] · `session_id` TEXT, UUID v4 de Claude [PLAN §12; POC-01] · `session_established` INTEGER 0/1 [PROPUESTA, regla 1] · `created_at`, `updated_at` [PLAN §12].
- `messages`: `id` TEXT (ULID, PK) [PLAN §12] · `conversation_id` FK · `role` TEXT ∈ {`user`, `orchestrator`, `system`} [PLAN §12]; en esta fase, `user` y `orchestrator` · `content` TEXT · `step_id` TEXT, ULID del turno que produjo o recibió el mensaje [PLAN §12] · `status` TEXT ∈ {`complete`, `error`} [PROPUESTA] · `idempotency_key` TEXT nulo; índice único (`conversation_id`, `idempotency_key`) cuando no es nulo [PLAN §25, §27] · `ts` [PLAN §12].
- `events`: PK (`conversation_id`, `seq`) [PLAN §12, §23] · `seq` INTEGER, 1, 2… por conversación, asignado en la misma transacción que la inserción · `ts` · `type` [PLAN §28] · `actor` ∈ {`claude`, `core`} [PLAN §12] · `step_id` TEXT nulo · `payload_json` TEXT, JSON [PLAN §12]. No tiene columna `id` autoincremental: el `id:` del SSE es `seq`.

`run_migrations(db_path)` aplica `upgrade head` desde el paquete, sin `alembic.ini` en el repositorio [PROPUESTA].

### 6.4 IDs [PLAN §12]

- Los IDs internos (conversación, mensaje y step) son ULID de 26 caracteres en Crockford base32. Los genera `core/ids.py` con la biblioteca estándar, sin dependencia externa [PROPUESTA]. Dentro del proceso son monótonos: dos IDs del mismo milisegundo se ordenan por orden de creación, así que `ORDER BY id` respeta el orden.
- El `session_id` de Claude es un UUID v4 que exige `claude --session-id` [POC-01]. Es un ID externo, no interno.
- Los IDs visibles `JOB-NNNNNN` no aplican: no hay Jobs en esta fase [PLAN §12].

### 6.5 Adaptadores y orquestador [PLAN §13, adaptado a la fase]

```python
@dataclass(frozen=True)
class RunSpec:
    session_id: str      # UUID v4 de la sesión de Claude
    resume: bool         # False -> --session-id; True -> --resume
    cwd: Path
    prompt: str          # se entrega por stdin, en UTF-8 [POC-01]

@dataclass(frozen=True)
class LaunchPlan:
    argv: tuple[str, ...]
    cwd: Path
    stdin_text: str
    env: Mapping[str, str] | None = None     # None: hereda el entorno

@dataclass
class ParseState:
    unparsed_lines: int = 0                  # solo contadores; nunca contenido
    result_seen: bool = False
    result_is_error: bool = False

@dataclass(frozen=True)
class NormalizedEvent:                       # [PLAN §13]: {type, ts, actor, step_id, data}
    type: str
    actor: str
    step_id: str | None
    data: dict[str, Any]
    ts: str | None = None                    # lo fija el núcleo al persistir

RunOutcome = Literal["ok", "failed", "invalid_output", "start_failed", "server_shutdown"]
# ok, failed, invalid_output: [PLAN §13]. start_failed y server_shutdown: extensiones [PROPUESTA]

class AgentAdapter(Protocol):                # [PLAN §13], subconjunto de la fase
    name: str
    def build_run(self, spec: RunSpec) -> LaunchPlan: ...
    def parse_line(self, line: bytes, state: ParseState) -> list[NormalizedEvent]: ...  # no lanza; [] si no aporta nada
    def classify_exit(self, code: int, state: ParseState) -> RunOutcome: ...

class OrchestratorAdapter(Protocol):         # [PLAN §13]
    name: str
    def chat(self, ctx: ConversationContext, message: str) -> AsyncIterator[NormalizedEvent]: ...
```

- `ConversationContext` [PROPUESTA] lleva `conversation_id`, `session_id`, `session_established` y `cwd` (el `workspace_dir` fijado al crear la conversación).
- `ClaudeAdapter` implementa `AgentAdapter` (`adapters/claude/adapter.py`). `build_run` produce el argv de 6.5.1.
- `ClaudeOrchestrator` implementa `OrchestratorAdapter.chat()` (`adapters/claude/orchestrator.py`) [PLAN §13]. Consume el proceso y emite `agent.message.delta`, `agent.message` y un evento interno `agent.result`. Al recibir `agent.message`, el texto completo sustituye a los fragmentos acumulados de ese mensaje (sección 3). Con `classify_exit` convierte el resultado en `step.finished`.
- `agent.result` es interno [PROPUESTA]: no se persiste ni se publica.
- `NormalizedEvent.step_id` sustituye al `step` del plan porque no hay steps de job. El `ts` lo fija el núcleo al persistir.
- No se emite razonamiento: los bloques `thinking` y `reasoning` se descartan en el parser [PLAN §13].

#### 6.5.1 argv de Claude [POC-01, POC-04, POC-08]

```
claude -p --output-format stream-json --verbose
  (sesión nueva: --session-id <uuid>   |   siguientes turnos: --resume <uuid>)
  [--model <claude_model>]
  --include-partial-messages
  --permission-mode default
  --disallowed-tools "Bash(codex:*)" "Bash(codex *)" "Bash(agy:*)" "Bash(agy *)" "Bash" "Write" "Edit" "MultiEdit" "NotebookEdit"
```

- El prompt va por stdin en UTF-8 [POC-01]. Nunca `--dangerously*`, `--last` ni `--sandbox`.
- `--permission-mode default` se fija siempre: no se hereda el modo global `auto` [POC-04, POC-08].
- Las denegaciones `Bash(codex:*)` y `Bash(codex *)` están confirmadas [POC-04]. `Bash`, `Write`, `Edit`, `MultiEdit` y `NotebookEdit` por nombre no están verificadas: el criterio 14(e) lo comprueba antes de aceptar la fase. El patrón `Bash(codex*)` del borrador anterior no está verificado y se retira.
- `--include-partial-messages` se añade siempre: POC-01b lo confirmó (sección 3).

#### 6.5.2 Parser (`parse_line`) [PLAN §13; POC-01]

- Decodifica UTF-8 con `errors="replace"` y aplica `json.loads`. Una línea vacía, que no es JSON o que no es un objeto devuelve `[]` e incrementa `state.unparsed_lines`, sin registrar el contenido.
- Despacha por `type`:
  - `assistant`: concatena, en orden, los bloques `text`; descarta los demás tipos de bloque. Sin texto devuelve `[]`. Si hay texto, emite `agent.message` con `data.text`.
  - `stream_event` (POC-01b): si `event.type == "content_block_delta"`, `event.delta.type == "text_delta"` y `parent_tool_use_id` es nulo, emite `agent.message.delta` con `data.text`. `message_start` reinicia el acumulado del mensaje. Cualquier otro `stream_event` (razonamiento, firmas, argumentos de herramientas, inicios y cierres de bloque) devuelve `[]`.
  - `result`: fija `state.result_seen` y `state.result_is_error`, y emite `agent.result` (`is_error`, `detail` solo si es error, `duration_ms`). El `result` no es la última línea: después llega `system/task_summary` [POC-01].
  - `system/*`, `rate_limit_event` y cualquier tipo desconocido devuelven `[]`. Su contenido no se reenvía ni se persiste.
- `classify_exit(code, state)`: `ok` si el código es 0 y el resultado no es error; `failed` si el código no es 0 o el resultado es error; `invalid_output` si el código es 0 y no hubo resultado. El `detail` de `step.finished` es `agent_error` o `process_exit`, según el caso.

### 6.6 Proceso [PLAN §30, §25; POC-06, POC-07]

`process/supervisor.py`, solo Windows:

```python
@dataclass
class RunHandle:
    pid: int
    create_time: float                # PID + create_time identifican el proceso [POC-07]
    output_path: Path
    stderr_path: Path

class Supervisor:
    def start(self, plan: LaunchPlan, *, output_path: Path, stderr_path: Path) -> RunHandle: ...
    def read_lines(self, handle: RunHandle) -> list[bytes]   # líneas completas nuevas desde el último offset
    def exit_code(self, handle: RunHandle) -> int | None     # None mientras el proceso vive
    def kill(self, handle: RunHandle) -> None                # árbol completo; idempotente
    def kill_all(self) -> None
```

- Sin `shell=True`. argv como lista. El prompt se escribe en stdin en UTF-8 y stdin se cierra. stdout y stderr van a archivos [POC-07].
- Cada proceso va en su propio Job Object, creado en `platform/windows.py` [PLAN §30], con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. `kill` termina el árbol entero [POC-06].
- Tras el evento `result`, el supervisor espera hasta 5 s a que el proceso salga y después lo mata. Claude sale unos 2,4 s después de `result` [POC-07] [PROPUESTA].
- `read_lines` lee en binario desde el último offset y entrega solo líneas terminadas en `\n`; el resto se retiene. Las líneas de más de 8 MiB se descartan y se cuentan [PROPUESTA].
- Las banderas de creación de proceso replican las de `pocs/common/procs.py` como referencia, sin importarlo [AGENTS.md].

### 6.7 Chat y bus de eventos [PLAN §8 `core.events`, §23]

- `core/chat.py` [PROPUESTA: la sección 30 no lo lista]. `ChatService` ofrece `create_conversation()`, `list_conversations()`, `get_conversation(id)`, `list_messages(id)` y `send_message(conversation_id, content, idempotency_key)`.
- `send_message` valida el contenido. En una transacción guarda el mensaje del usuario, con un `step_id` nuevo, y el evento `step.started`. Hace commit, publica y lanza el turno en segundo plano sin esperar a Claude.
- Bucle del turno, cada ≤200 ms: `read_lines` → `parse_line` → persistir (evento y mensaje en una transacción) → publicar. Al salir el proceso: última lectura completa y `step.finished`. El registro de turnos activos está en memoria.
- `core/events.py` [PLAN §8]: `EventBus` con `publish(conversation_id, event)` y `subscribe(conversation_id)`, que es un iterador asíncrono. Cola acotada de 1000 eventos por suscriptor: si se llena, se cierra esa suscripción y el cliente resincroniza. La desconexión libera la suscripción. Se publica solo después del commit [PLAN §23].
- Un único proceso de servidor [PLAN §7].

### 6.8 API HTTP [PLAN §27, adaptado]

Prefijo `/api`. JSON. Errores con la forma del plan: `{"error": {"code": "...", "message": "...", "details": {}}}` [PLAN §27]. Mutaciones con `Idempotency-Key` [PLAN §25, §27]. CSRF llega en la Fase 4.

| Método y ruta | Cuerpo y cabeceras | Respuesta | Errores |
|---|---|---|---|
| GET `/` y GET `/assets/*` | — | Archivos de `web/dist` | — |
| GET `/api/conversations` | — | 200 `[{id, title, updated_at}]`, por `updated_at` descendente | — |
| POST `/api/conversations` | `{}` | 201 `{id, title, created_at, updated_at}` | — |
| GET `/api/conversations/{id}` | — | 200 `{id, title, created_at, updated_at}` | 404 `conversation_not_found` |
| GET `/api/conversations/{id}/messages` | — | 200 `{messages: [{id, step_id, role, content, status, ts}], active_step: null o {step_id}}`, en orden por `id` | 404 |
| POST `/api/conversations/{id}/messages` | Cabecera `Idempotency-Key` obligatoria (1–128 caracteres). Cuerpo `{"content": str}`, de 1 a 100 000 caracteres y no solo espacios | 202 `{message: {id, step_id, role, content, status, ts}}`. Si la clave ya existe en la conversación: 200 con la misma respuesta, sin turno nuevo | 400 `missing_idempotency_key`; 404; 409 `turn_in_progress`; 415; 422 `invalid_body` |
| GET `/api/stream?conversation={id}` [D-16, C-1] | — | `text/event-stream` (6.9) | 404; 422 si falta el parámetro |

- `GET /api/conversations` y `GET /api/conversations/{id}` son [PROPUESTA]: la sección 27 no las enumera, pero la lista de conversaciones es tarea de la Fase 1 [PLAN §36].

### 6.9 SSE [PLAN §23, §28; C-1]

Formato por evento, con los nombres de §28 cambiando `job` por `conversation`. La clave JSON es `step`, como en §28: `NormalizedEvent.step_id` y la columna `events.step_id` se serializan siempre como `"step"` en el SSE:

```
id: 17
event: conversation.event
data: {"conversation":"<id>","seq":17,"ts":"2026-10-03T15:00:00Z","type":"agent.message","actor":"claude","step":"<step_id>","data":{"message_id":"<id>","text":"…"}}

: ping
```

Línea `: ping` cada 15 s [PLAN §23]. Tipos de la fase, con los nombres de §28:

| `type` | `actor` | `data` |
|---|---|---|
| `step.started` | `core` | `kind` = `chat`, `agent` = `claude`, `message_id` del mensaje del usuario |
| `agent.message.delta` | `claude` | `message_id` (el del mensaje en curso, asignado al primer fragmento) y `text` (solo el fragmento nuevo). Persistido coalescido cada ~500 ms (sección 3) |
| `agent.message` | `claude` | `message_id`, `text` |
| `step.finished` | `core` | `kind` = `chat`, `agent` = `claude`, `outcome` (`ok`, `failed`, `invalid_output`, `start_failed`, `server_shutdown`), `duration_ms`, `message_id` del mensaje de error si lo hay, `detail` (≤300 caracteres) si lo hay |

- **Reconexión** [PLAN §23, §29]: en esta fase el servidor no reenvía eventos anteriores (no hay replay con `Last-Event-ID`). Esa función es de la Fase 2 (criterio 4 de su plan). El cliente deduplica por `seq` y, tras reconectar, recarga los mensajes.
- Un stream por pestaña [PLAN §23, límite HTTP/1.1]. Se abre antes de cargar los mensajes, para no perder eventos entre ambas operaciones (6.10).

### 6.10 Web [PLAN §29, §30]

- Stack [PLAN §29]: React, TypeScript y Vite. TanStack Query para el estado del servidor. React Router en modo hash (`createHashRouter`) [PROPUESTA: no requiere reescritura de rutas en el servidor]. Un hook `useEventStream`. CSS modules [PLAN §29: se elige la opción de módulos, sin Tailwind ni Pico]. Texto plano (D-16, C-3). Sin librería de componentes.
- Esquema de interfaz de agente (D-15): barra lateral con la lista de conversaciones y el botón «Nueva conversación»; panel principal con el chat, la respuesta en streaming y el indicador de actividad. En móvil, la barra lateral se pliega en un menú. Las secciones de repositorios y tareas se añaden en fases posteriores sin cambiar este esquema.
- Rutas: `#/` muestra la lista; `#/c/<id>` muestra la conversación activa.
- Hook `useEventStream(conversationId, onEvent)`: abre `EventSource('/api/stream?conversation=<id>')`. Ignora los eventos con `seq` menor o igual al último visto. Tras un error y la reconexión, invalida la consulta de mensajes para resincronizar [PLAN §29].
- Al abrir una conversación: primero se abre el stream y después se carga `GET /api/conversations/{id}/messages`. Los mensajes se deduplican por `id` [PROPUESTA].
- Al enviar: se genera una `Idempotency-Key` (UUID v4) por envío. Enter envía y Mayús+Enter salta de línea. El botón se deshabilita mientras haya un turno activo, es decir, entre `step.started` y `step.finished` [PROPUESTA].
- Al recibir `step.finished`, se invalida la lista de conversaciones para actualizar `updated_at` [PROPUESTA].
- Indicador «Claude está respondiendo…» entre `step.started` y `step.finished` [PROPUESTA].
- Seguridad de render [PLAN §26, T13]: todo texto que llega del servidor se muestra como texto de React. Prohibidos: `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` y `new Function`.
- Responsive [PLAN §29]: una columna por debajo de 768 px. Incluye `<meta name="viewport" content="width=device-width, initial-scale=1">`. El campo de envío es visible a 390 px de ancho sin desplazamiento horizontal.
- Textos de la interfaz en español [PROPUESTA].
- Compilación [PLAN §32]: `npm --prefix web ci` y `npm --prefix web run build`, que genera `web/dist`. `dist/` está en `.gitignore`.
- Pruebas [PLAN §35]: Vitest y Testing Library para el hook (deduplicación por `seq`) y para el render de texto malicioso.

### 6.11 CLI [PLAN §31, §32]

`relayforge serve [--port N]`:
1. Carga y valida `Settings` con la precedencia de 6.2.
2. Resuelve el ejecutable de Claude.
3. Comprueba que existe `web/dist/index.html`. Si falta, sale con código 2 e indica `npm --prefix web run build`.
4. Crea `<home>` con `config/`, `data/` y `logs/`, y aplica las migraciones.
5. Arranca uvicorn con `host="127.0.0.1"`, un solo proceso y sin recarga. Imprime la URL.

Códigos de salida: 0 apagado normal; 2 configuración o entorno inválido, con un mensaje sin valores sensibles; 1 error inesperado. No existe `--host`.

El log de la aplicación va a `<home>/logs/relayforge.log` [PLAN §24], sin texto de mensajes (regla 8). La rotación queda para la Fase 10 [PROPUESTA].

### 6.12 Agente falso [PLAN §30, §35]

`tests/fakes/fake_agent.py`, ejecutado con `python -X utf8`. Imita la CLI de Claude:
- acepta los argumentos de `build_run`, lee el prompt de stdin y escribe con `flush` líneas JSON con la forma de las capturas de POC-01, no de la memoria;
- el escenario se elige con `FAKE_AGENT_SCENARIO`: `ok`; `two_messages` (dos mensajes separados ≥1 s); `blocks` (un mensaje con bloques de texto, razonamiento y herramienta, con un marcador único en cada bloque, en `system/init` y en stderr); `error_result`; `exit_nonzero`; `no_result`; `partial_lines` (una línea escrita en dos partes que corta un carácter multibyte); `spawn_children` (proceso → hijo → nieto, todos vivos);
- `FAKE_AGENT_LOG` apunta a un JSON con el `argv`, el prompt y la marca de cada línea escrita;
- las pruebas de CLI lo exponen con un lanzador `.cmd` temporal, usado como `RELAYFORGE_CLAUDE_BIN`.

## 7. REGLAS DE NEGOCIO Y CASOS LÍMITE

1. **Sesión de Claude.** `session_id` (UUID v4) se genera al crear la conversación. El primer turno con sesión nueva usa `--session-id`; los siguientes usan `--resume` con el mismo UUID [POC-01]. Una sesión que murió antes del primer mensaje del modelo no se puede reanudar («No conversation found») [POC-07]. Por eso `session_established` pasa a 1 al recibir el primer `agent.message` de la conversación. Mientras sea 0, el siguiente turno genera un UUID nuevo, lo guarda y usa `--session-id`, nunca `--resume`. `workspace_dir` se fija al crear la conversación y se usa en todos sus turnos, aunque cambie el ajuste [PROPUESTA; criterio 14].
2. **Un turno activo por conversación.** Un segundo POST con turno activo devuelve 409 `turn_in_progress`, sin guardar nada ni lanzar un proceso. Conversaciones distintas pueden tener turnos simultáneos. Un solo proceso de servidor.
3. **Idempotencia** [PLAN §25]. `Idempotency-Key` es obligatoria en el POST de mensajes. Una clave ya usada en la conversación devuelve 200 con la respuesta original, sin mensaje ni turno nuevos. Sin clave, 400.
4. **Orden y persistencia** [PLAN §23]. Se persiste antes de publicar. El orden de un turno es: `step.started` → 0..n `agent.message.delta` → un `agent.message` por mensaje completo (su texto sustituye a los fragmentos) → exactamente un `step.finished`. Cada evento se guarda en `events` con el siguiente `seq` de su conversación, en la misma transacción que su mensaje si lo tiene. Después del commit, se publica.
5. **Cierre y errores** [PLAN §13]. `step.finished.outcome` es `ok` si `classify_exit` da `ok`; `failed` (con `detail` `agent_error` o `process_exit`); `invalid_output` si no hubo resultado; `start_failed` si el proceso no se pudo lanzar; `server_shutdown` al apagar. `start_failed` y `server_shutdown` son extensiones [PROPUESTA]. Un turno fallido guarda un mensaje `orchestrator` con `status="error"` y un texto breve en español; si hay `detail`, se recorta a 300 caracteres. Los mensajes del asistente ya guardados se conservan. Tras un fallo, la conversación acepta mensajes nuevos.
6. **Parser tolerante** [PLAN §37]. Ignora lo desconocido. Cuenta las líneas que no interpreta, sin registrar su contenido. Una línea mala nunca interrumpe el turno. La versión de Claude Code forma parte de la ruta de cada fixture.
7. **Archivos de salida** [PLAN §24]. El stdout y el stderr de cada turno van a `<home>/data/conversations/<conversation_id>/steps/<step_id>/stdout.ndjson` y `stderr.log`. El sondeo es de ≤200 ms, y tras la salida del proceso se hace una última lectura completa. Sin limpieza en esta fase. La API no los sirve.
8. **Datos que nunca salen** [PLAN §36, criterio 4]. La API, el SSE, la base de datos y la web solo contienen el texto de los bloques `text` del asistente, el texto del usuario y los mensajes de error propios. Nunca razonamiento, herramientas, `system/*` ni stderr. Los logs no incluyen texto de mensajes, solo IDs, tipos y tamaños.
9. **Seguridad mínima** [PROPUESTA; no sustituye a las fases 4 y 10]. El bind es fijo en `127.0.0.1` [PLAN §36, criterio 5]. Un `Host` distinto de `127.0.0.1` o `localhost` recibe 400 `invalid_host`, para evitar DNS rebinding. Un POST sin `Content-Type: application/json` recibe 415. Un POST con `Origin` ajeno recibe 403 `forbidden_origin`. No hay CORS. Las respuestas de la web llevan `Content-Security-Policy: default-src 'self'`.
10. **Postura solo chat** [PLAN §14, §36]. Se aplica el argv de 6.5.1. El criterio 14(e) verifica con Claude real que no se crea ningún archivo y que no se delega en otra CLI. Si falla, la fase no se acepta hasta endurecer las restricciones.
11. **Apagado** (Ctrl+C). Se ejecuta `kill_all`. Cada turno activo recibe `step.finished` con `server_shutdown` si es posible, y se guarda un mensaje `error`. Si el proceso muere de forma abrupta, el Job Object termina a sus hijos. El turno puede quedar sin cierre, pero la conversación no se bloquea, porque el registro de turnos está en memoria. La recuperación es de la Fase 2 [PLAN §25].
12. **Sin timeout ni cancelación por el usuario** [PLAN §36]. Son de la Fase 8. Un turno bloqueado se resuelve reiniciando el servidor.
13. **Fixtures** [PLAN §30; POC-01]. `tests/fixtures/claude/2.1.283/` se deriva de capturas reales de Claude Code, nunca se inventa. Las capturas crudas de POC-01 no están en el árbol de la laptop, y en la PC principal `pocs/results/` solo conserva las de POC-03 y POC-05 [POC_RESULTADOS]. Fuente: las capturas reales y saneadas de POC-01b en `pocs/results/poc01b/claude-2.1.283/` (sección 3), que Codex copia sin cambios a `tests/fixtures/claude/2.1.283/` y verifica de nuevo (sin rutas personales ni listas de skills). Se recorta y se sanea: sin rutas personales, credenciales, listas de skills ni servidores MCP. Si falta, Codex **no la inventa**: se detiene y lo comunica. Los casos de error, razonamiento y herramienta se construyen en línea en cada prueba y se etiquetan como sintéticos.
14. **Plataforma y rutas.** Solo Windows. `relayforge serve` funciona desde cualquier directorio de trabajo. UTF-8 sin BOM y LF [AGENTS.md].
15. **Build de la web.** `relayforge serve` no compila la web. Si falta `web/dist`, sale con código 2 (6.11).

## 8. CRITERIOS DE ACEPTACIÓN

1. **Alcance.** `git status` muestra solo los archivos de la sección 5. `pocs/**`, `docs/PLAN_PROYECTO.md`, `docs/POC_RESULTADOS.md`, `docs/specs/**` y `README.md` no cambian. `git grep --untracked -nE "(import|from) pocs" -- src tests` no devuelve coincidencias.
2. **Calidad.** Desde la raíz, con código 0: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv run pytest`. Con código 0 también: `npm --prefix web ci`, `npm --prefix web run lint`, `npm --prefix web run typecheck`, `npm --prefix web run test` y `npm --prefix web run build`. El resultado es el mismo con un `PATH` sin `claude`, `codex` ni `agy`. Ninguna prueba usa CLIs reales.
3. **Parser** (`test_claude_parser.py`, con las fixtures de POC-01b). Extrae el texto de `assistant`. Localiza `result` por `type`, aunque no sea la última línea. Descarta `system/*` y `rate_limit_event`. Ignora una línea vacía, un JSON inválido, un objeto sin `type` y los tipos desconocidos, sin lanzar excepciones. Con un mensaje sintético que mezcla bloques `text`, de razonamiento, de herramienta y desconocidos, devuelve solo el `text`. Reconoce `is_error=true`.
4. **Latencia del pipeline.** Con `two_messages` y un cliente SSE real (uvicorn en un hilo, puerto efímero en `127.0.0.1`), cada `agent.message` llega ≤1 s después de que el agente falso escriba su línea [PLAN §36].
5. **Streaming de fragmentos** [PLAN §23, §36 criterio 1]. Con Claude real, los primeros fragmentos aparecen en menos de 2 s tras el primer token [umbral de POC-01, §38.2]. El texto se actualiza al menos dos veces antes de `step.finished`. El texto final coincide con el mensaje completo, sin duplicados. Con el agente falso (`two_messages` emitiendo `stream_event`/`text_delta` con la forma de POC-01b), se verifica lo mismo: los fragmentos se ven antes del mensaje completo y el texto final no se duplica.
6. **Sesión y contexto** [PLAN §36 criterio 2]. Pruebas unitarias: el primer turno usa `--session-id <uuid>` y no `--resume`; el segundo usa `--resume` con el mismo UUID; si el primer turno no produjo mensaje del asistente, el siguiente usa un UUID nuevo y `--session-id`. `--permission-mode default` y `--disallowed-tools` con los patrones de 6.5.1 están siempre presentes. Nunca aparece `--dangerously*`. Manual (criterio 14): el segundo mensaje depende del primero y la respuesta lo refleja.
7. **Persistencia y recarga** [PLAN §36 criterio 3]. Integración: tras varios turnos, crear la aplicación de nuevo sobre la misma base devuelve las mismas conversaciones y mensajes, en el mismo orden e incluidos los de `status="error"`. Manual: F5 con la conversación abierta (`#/c/<id>`) y cerrar y reabrir la pestaña reconstruyen la conversación.
8. **Sin razonamiento ni metadatos** [PLAN §36 criterio 4]. Con `blocks`, ninguno de los marcadores aparece en las respuestas de la API, en los eventos SSE ni en las filas de `messages` o `events`. La búsqueda en `web/src` no encuentra las funciones de render HTML de 6.10. La interfaz no los muestra (criterio 14).
9. **Bind local y seguridad mínima** [PLAN §36 criterio 5]. Con el servidor en marcha, `psutil.net_connections()` muestra el puerto 8787 solo en `127.0.0.1`, no en `0.0.0.0` ni en `::`. No existe ajuste ni variable de host. Un `Host` ajeno da 400, un POST con `Origin` ajeno da 403 y un POST sin JSON da 415. La web responde con `Content-Security-Policy: default-src 'self'`.
10. **Supervisor** (`test_supervisor.py`). `read_lines` entrega cada línea una vez, sin pérdidas ni duplicados. Retiene una línea parcial hasta completarla y no corrompe un carácter UTF-8 partido entre escrituras (`partial_lines`). Descarta y cuenta una línea de más de 8 MiB sin fallar. Con `spawn_children`, `kill` deja 0 descendientes (psutil) y es idempotente. `kill_all` termina todos los procesos.
11. **Concurrencia y errores.** Un segundo POST con turno activo devuelve 409 sin un segundo proceso. `error_result`, `exit_nonzero` y `no_result` producen `step.finished` con `outcome` `failed`, `failed` e `invalid_output`, y un mensaje `orchestrator` con `status="error"`; el siguiente mensaje de la conversación funciona. Un ejecutable inexistente produce `start_failed`. Una conversación inexistente da 404. Un contenido vacío, solo de espacios o de más de 100 000 caracteres da 422. Sin `Idempotency-Key` da 400. Una clave repetida devuelve 200 con la misma respuesta y sin turno nuevo.
12. **Base de datos.** `upgrade head` sobre una base vacía crea exactamente `conversations`, `messages` y `events`, además de la tabla de versión de Alembic. `relayforge serve` aplica las migraciones al arrancar. `downgrade base` deja la base sin tablas de la aplicación. `PRAGMA foreign_keys` es 1, `journal_mode` es `wal` y `busy_timeout` es 5000.
13. **Arranque y configuración.** `relayforge serve` con `workspace_dir` válido arranca desde otro directorio, responde 200 en `GET /` y sale con código 0 al apagarse. Un `workspace_dir` inexistente, un `claude` que no se resuelve o la falta de `web/dist` dan código 2 con un mensaje sin valores sensibles. `test_settings.py` comprueba la precedencia: CLI, después entorno, después `settings.yaml` y por último valores por defecto.
14. **Prueba manual con Claude real y de interfaz** (la ejecuta el usuario o el coordinador; `AGENTS.md` prohíbe automatizarla). Registrar en `docs/ESTADO_TRABAJO.md` la fecha, la versión de Claude Code y el resultado de:
    - (a) criterio 5 en la versión aprobada;
    - (b) criterio 6, manual;
    - (c) criterio 7, manual;
    - (d) interfaz sin razonamiento ni metadatos;
    - (e) solo chat: pedir que cree un archivo en el repositorio de trabajo y que ejecute `codex --version`. No se debe crear ningún archivo (`git status --porcelain` igual antes y después) ni delegar en otra CLI. Aquí se verifican también las denegaciones por nombre (`Bash`, `Write`, `Edit`), que aún no están confirmadas;
    - (f) con 390 px de ancho, una columna y el campo de envío visible.
15. **Higiene.** Sin `shell=True` ni flags `dangerously*`. Ningún archivo nuevo contiene rutas personales (búsqueda de rutas de home Windows, macOS y Unix, y del usuario local), credenciales ni contenido de `.env`. `.env.example` no tiene valores secretos. UTF-8 sin BOM y LF. `LICENSE` es el texto oficial de Apache-2.0 sin modificar.
16. **Separación de fases.** Las rutas HTTP y SSE son exactamente las de 6.8 y 6.9, y las tablas son exactamente las de 6.3. No existen módulos ni rutas de Jobs, workflows, repositorios, worktrees, Codex, Antigravity, políticas, aprobaciones, autenticación ni `doctor` (búsqueda de texto y listado de rutas).

## 9. RIESGOS Y REVERSIÓN

- [PLAN §37] El formato de stream-json cambia entre versiones → parser tolerante y fixtures por versión (reglas 6 y 13).
- Los fragmentos dependen de un formato no documentado públicamente de `stream_event` (POC-01b, 2.1.283) → parser tolerante, fixtures por versión y criterio 5 con Claude real.
- Sin capturas reales no hay fixtures fiables. Es una precondición, no un detalle de las pruebas (regla 13).
- La configuración global del usuario (skills, memorias y servidores MCP) se carga también en `-p` [POC-01] y puede inducir delegación o herramientas no deseadas. La mitigación de 6.5.1 se verifica con Claude real en el criterio 14(e).
- El plan usa `Bash(codex*)` en §14 y §17, un patrón no verificado. Esta fase no lo usa. Hay que corregir el plan cuando se apruebe esta especificación [POC-04].
- Node.js y Vite: la laptop necesita Node para compilar la web. La versión queda registrada en `docs/ESTADO_TRABAJO.md`.
- Reversión [PLAN §36]: fase aislada; revertir el commit. La base de datos y los archivos de salida viven en `<home>`, fuera del repositorio.

## 10. CAMBIOS DE ALINEACIÓN (2026-10-03)

Respecto al borrador anterior (versión de la laptop). No cambian el alcance ni la fase; sí los nombres y decisiones necesarios para cumplir el plan.

| Tema | Borrador anterior | Versión alineada | Plan |
|---|---|---|---|
| IDs internos | UUID v4 para conversación y turno | ULID generado por `core/ids.py` | §12 |
| UUID de Claude | UUID v4 | Se mantiene: formato que exige `--session-id` | §12 (`session_id`), POC-01 |
| `conversations` | `id` UUID, `claude_session_id` | `id` ULID, `session_id`, `orchestrator`, `workspace_dir` (en lugar de `repo_id`) | §12 |
| `messages` | `role` user/assistant, `turn_id`, `created_at` | `role` user/orchestrator, `step_id`, `ts`, `status`, `idempotency_key` | §12, §25, §27 |
| `events` | `id` autoincremental global, `turn_id` | PK (`conversation_id`, `seq`), `step_id`, `payload_json` | §12, §23 |
| Ruta del SSE | `GET /api/stream` | `GET /api/stream?conversation={id}` (**C-1, pendiente**) | §28, §36 |
| Formato del SSE | `event: <tipo>`, `assistant.message`, `turn.*` | `event: conversation.event` con `type` dentro; `step.started/finished` (kind `chat`), `agent.message`, `agent.message.delta` | §28, §12 (kind `chat`) |
| Reconexión | Solo recarga | Deduplicación por `seq` en el cliente, resincronización al reconectar; replay con `Last-Event-ID` en la Fase 2 | §23, §29, Fase 2 criterio 4 |
| Heartbeat | 15 s, referenciado a FASE_0C | 15 s, referenciado a §23 | §23 |
| Fragmentos | No definidos | En vivo; persistidos coalescidos (~500 ms) más el mensaje completo | §23 (POC-01b) |
| Idempotencia | No definida | `Idempotency-Key` obligatoria en el POST de mensajes | §25, §27 |
| Errores de la API | No definidos | `{"error": {"code", "message", "details"}}` | §27 |
| Adaptadores | `build_command`, `parse_line` sin estado, `AgentEvent` | `build_run(RunSpec) -> LaunchPlan`, `parse_line(line, ParseState)`, `classify_exit`; `ClaudeOrchestrator.chat()` | §13 |
| Resultados del turno | Motivos `agent_error`, `process_exit`, `no_result` | `outcome` de §13 (`ok`, `failed`, `invalid_output`) y dos extensiones | §13 |
| Stack web | JavaScript sin compilación | React, TypeScript y Vite en `web/`, con TanStack Query, React Router en modo hash, hook `useEventStream` y CSS modules; responsive | §29, §30, §32 |
| Ubicación de `web/` | `src/relayforge/web/` | `web/` en la raíz, como indica §30 | §30 |
| Estructura del paquete | `chat.py`, `bus.py`, `adapters/claude/parser.py` en la raíz del paquete | `core/chat.py`, `core/events.py`, `adapters/claude/`, `platform/windows.py`, `api/routes/` | §8, §30 |
| Configuración | Ajustes con nombres propios, `.env` leído, `claude_model` marcado como §31 | Precedencia de §31 (valores por defecto, `settings.yaml`, entorno, CLI); nombres de §31 cuando existen; `claude_model` marcado como propuesta | §31 |
| Archivos de salida | `<home>/runs/` | `<home>/data/conversations/<id>/steps/<step_id>/` | §24 |
| Denegaciones de Claude | `Bash(codex*)` (no verificado) | `Bash(codex:*)` y `Bash(codex *)` (confirmados en POC-04), más `Bash` y escritura por nombre (a verificar) | §38.1, §38.2 |
| Fixtures y fake | `tests/fixtures/claude/*.jsonl`, `tests/fakes/fake_claude.py` | `tests/fixtures/claude/2.1.283/*.ndjson`, `tests/fakes/fake_agent.py` | §30, §35 |
| Pruebas de la web | Ninguna | Vitest y Testing Library (hook y render sin HTML) | §35 |
| Comprobaciones | Solo Python | Ruff, mypy, pytest y las comprobaciones de la web (lint, tsc, vitest, build) | §35 |

**Conflictos C-1, C-2 y C-3:** resueltos por el usuario (D-16, sección 4).
