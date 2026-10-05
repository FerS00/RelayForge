> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Especificación técnica — Fase 2

- Estado: **Completada** (2026-10-04). Antigravity: APROBADO; los 8 criterios aceptados y los 10 comandos de auditoría terminaron con código 0.
- Responsable de especificación e implementación: Codex, por continuidad sin Claude.
- Auditor independiente: Antigravity, sujeto a autenticación y disponibilidad del runner.
- Evidencia local: `uv run ruff check`, `uv run ruff format --check` (52 archivos), `uv run mypy` (38 archivos), `uv run pytest -q` (44 passed), `npm --prefix web run lint`, `typecheck`, `test` (5 passed) y `build`: PASS.
- Limitación observada: pytest informa una advertencia deprecada de Starlette sobre `httpx`; no bloquea la fase.
- Base: `docs/PLAN_PROYECTO.md`, secciones 11, 12, 23, 25 y Fase 2.

## Objetivo

Crear Jobs persistidos para el flujo de planificación, validar sus transiciones, recuperar el historial SSE tras reconectar y dejar los Jobs activos como `INTERRUPTED` al reiniciar el backend si no se implementa seguimiento reanudable del proceso. No se inicia implementación de repositorios, worktrees, Codex, checks, auditoría ni entrega; pertenecen a fases posteriores.

## Rutas afectadas

- `src/relayforge/db/models.py`
- `src/relayforge/db/migrations/versions/0002_jobs.py`
- `src/relayforge/core/states.py`
- `src/relayforge/core/jobs.py`
- `src/relayforge/core/events.py`
- `src/relayforge/core/scheduler.py`
- `src/relayforge/process/reconcile.py`
- `src/relayforge/adapters/base.py`
- `src/relayforge/adapters/claude/adapter.py`
- `src/relayforge/adapters/claude/orchestrator.py`
- `src/relayforge/api/app.py`
- `src/relayforge/api/schemas.py`
- `src/relayforge/api/routes/jobs.py`
- `src/relayforge/api/routes/stream.py`
- `config/schemas/plan.schema.json`
- `web/src/App.tsx`
- `web/src/api.ts`
- `web/src/pages/Dashboard.tsx`
- `web/src/pages/NewTask.tsx`
- `web/src/pages/JobDetail.tsx`
- `web/src/styles.module.css`
- `tests/unit/test_states.py`
- `tests/unit/test_jobs.py`
- `tests/integration/test_jobs_api.py`
- `tests/integration/test_job_events_sse.py`
- `tests/integration/test_job_reconcile.py`
- `tests/integration/test_db_migrations.py`
- `tests/fakes/fake_agent.py`
- `web/src/pages/Dashboard.test.tsx`
- `web/src/pages/NewTask.test.tsx`
- `web/src/pages/JobDetail.test.tsx`

## Datos y contratos

- `JobStatus`: enum con los estados y transiciones de la sección 11 del plan. `JobService.transition(job_id, target, expected_version=None)` valida la arista, actualiza `status` con una guarda atómica de `version` y `status`, incrementa `version` y agrega `job.state_changed` dentro de una transacción. Estados terminales no tienen transiciones.
- `Job`: `id` ULID, número visible secuencial (`JOB-NNNNNN`), `title`, `request_text`, `workflow="plan"`, `status`, `conversation_id`, `approval_kind`, `iteration`, `max_iterations`, `orchestrator_session_id`, marcas de tiempo UTC, `version`, `error_code` y `error_message` saneado.
- `JobStep`: `id`, `job_id`, `kind`, `agent`, `iteration`, `status`, `started_at`, `heartbeat_at`, `finished_at`, `resume_token`, `resumable`, `attempt`, `summary_json`, `error_code`.
- `Artifact`: `id`, `job_id`, `step_id`, `kind`, `path`, `sha256`, `size`, `redacted`, `created_at`. Esta fase no escribe artefactos; se crea la tabla para el contrato del plan.
- `Job.conversation_id` referencia una conversación propia. `Event.job_id` es opcional para conservar eventos de Fase 1. El `seq` sigue aumentando por conversación conforme a D-16; un stream de Job filtra por `job_id` y usa ese `seq` como cursor.
- `POST /api/jobs` recibe `{title, request_text, workflow?}` y `Idempotency-Key`; acepta solo `workflow="plan"`, devuelve 202 `{job}` y coloca el Job en `QUEUED`.
- `GET /api/jobs` devuelve Jobs ordenados por actualización descendente; `GET /api/jobs/{id}` devuelve Job, plan si existe y pasos; `GET /api/jobs/{id}/events` entrega SSE con `Last-Event-ID`; `POST /api/jobs/{id}/cancel` solicita cancelación idempotente.
- `GET /api/jobs/{id}/events` responde 404 si el Job no existe, 400 si el cursor no es un entero no negativo y vuelve a emitir solo eventos con `seq > Last-Event-ID`. La suscripción se establece antes de consultar la base; eventos duplicados del búfer se descartan por `seq`.
- `ClaudeOrchestrator.plan(ctx, request_text)` devuelve `PlanResult(objective, summary, steps, risks)` tras validar la salida contra `config/schemas/plan.schema.json`. La respuesta estructurada se persiste como `job.plan` y el Job termina `COMPLETED` en este flujo provisional.

## Reglas y fallos

1. Un Job y su conversación se crean en una transacción; una clave de idempotencia repetida no crea otro Job ni otro evento.
2. El scheduler inicia como máximo un Job de planificación por `workspace_dir`; los demás permanecen en `QUEUED`.
3. Cada cambio de estado y su evento se confirman atómicamente. Rechazar transición no cambia filas ni emite evento.
4. Un fallo de agente deja Job `FAILED` con código genérico y mensaje saneado; logs o stderr no se exponen por API.
5. Cancelar un Job en cola lo termina como `CANCELLED`. Cancelar uno activo pasa por `CANCELLING`, cancela el task y espera el cierre del proceso supervisado antes de `CANCELLED`.
6. Al iniciar el backend, Jobs previamente activos sin proceso reanudable se marcan `INTERRUPTED`; `WAITING_*`, `QUEUED` y terminales se conservan. La reanudación automática de logs de procesos vivos queda fuera de esta fase; POC-07 permite el estado alternativo si el seguimiento se implementa después.
7. La migración nueva preserva datos existentes de Fase 1; downgrade elimina solo los datos/tablas añadidos por Fase 2 y restaura la forma anterior de `events`/`conversations` sin borrar mensajes.
8. No se ejecutan CLIs reales de agentes durante pruebas. Toda prueba de plan usa un fake y archivos temporales.

## Criterios de aceptación

1. La tabla de estados rechaza toda transición no permitida y mantiene inmutables los estados terminales.
2. Crear/listar/abrir un Job conserva el Job, el plan, la conversación y sus pasos tras reconstruir la app con la misma base SQLite.
3. Forzar cierre/reinicio con un Job activo lo deja `INTERRUPTED` sin estado activo huérfano; Jobs terminales y en espera conservan su estado.
4. El replay SSE con `Last-Event-ID` no pierde ni duplica eventos al reconectar entre persistencia y suscripción.
5. La web ofrece Dashboard, formulario New Task y detalle del Job con estado, plan, timeline y reconexión SSE.
6. Pruebas unitarias e integración usan fakes; ninguna invoca Claude, Codex o Antigravity CLI.
7. Ruff, mypy, pytest, lint, typecheck, Vitest y build pasan. Resultados de cada comando se informan por separado.
8. Migración upgrade/downgrade conserva datos de Fase 1 y `git diff --check` no reporta errores.

## Comprobaciones autorizadas para la auditoría

- `uv run ruff check`
- `uv run ruff format --check`
- `uv run mypy`
- `uv run pytest -q`
- `npm --prefix web run lint`
- `npm --prefix web run typecheck`
- `npm --prefix web run test`
- `npm --prefix web run build`
- `git diff --check`

Todos son checks locales existentes; usan fakes y no realizan escrituras externas. El auditor puede inspeccionar solo los archivos enumerados en la especificación, el diff y la salida de estos checks.
