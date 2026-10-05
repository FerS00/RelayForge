> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Especificación técnica — Fase 8

Estado: En curso (2026-10-04). Codex especifica e implementa sin Claude; Antigravity audita en solo lectura. Complejidad alta por concurrencia, recuperación y supervisión de procesos. Esfuerzo aplicado a Antigravity: high; esfuerzo efectivo de Codex del turno: el configurado por la sesión, no modificable desde un prompt.

## Objetivo

Completar la recuperación definida en §25.1–25.2 de `docs/PLAN_PROYECTO.md`: cancelación que cierre los procesos del paso, heartbeat y timeout, clasificación conservadora de errores transitorios, espera `WAITING_RETRY` con `retry_at`, reanudación explícita de Jobs `INTERRUPTED`, reconciliación de estados activos y persistencia del estado de salud del agente.

## Contratos

- `Job.retry_at` y el contador de reintentos son persistentes. Solo errores clasificados como rate limit o red pueden programar un intento; el backoff tiene un máximo y nunca forma un bucle automático. Errores de autenticación, salida inválida y configuración no se reintentan automáticamente.
- Rate limit actualiza la salud del agente como `RATE_LIMITED`; fallo de autenticación como `AUTH_REQUIRED`; errores no reconocidos como `UNKNOWN`. No guardar texto bruto de errores en el estado de salud.
- Un heartbeat actualiza `JobStep.heartbeat_at`; timeout duro mata el árbol y termina el paso con `TIMED_OUT`. El cierre del backend o la cancelación no dejan Jobs activos sin un proceso identificado.
- `POST /api/jobs/{id}/resume` acepta `{mode: resume_session|retry_step}` solo para `INTERRUPTED`. `resume_session` exige un token persistido; `retry_step` reinicia el paso interrumpido en una nueva ejecución. La operación es idempotente frente a una reanudación concurrente.
- Los Jobs `WAITING_RETRY` no se ejecutan al arrancar antes de `retry_at`; cuando vence la hora, vuelven a la cola una vez. No se reanudan automáticamente Jobs `INTERRUPTED`.
- Los worktrees de Jobs `INTERRUPTED`, `WAITING_RETRY` o `WAITING_APPROVAL` se conservan. Solo se limpian recursos temporales de Jobs terminales mediante ruta contenida bajo el runtime.

## Rutas afectadas

- `docs/specs/FASE_8.md`, `docs/PLAN_PROYECTO.md`, `docs/ESTADO_TRABAJO.md`
- `src/relayforge/core/{jobs.py,scheduler.py,states.py}`
- `src/relayforge/db/{models.py,migrations/versions/0007_job_reliability.py}`
- `src/relayforge/process/{supervisor.py,reconcile.py}`
- `src/relayforge/core/{workflow.py,checks.py,audit.py}`
- `src/relayforge/adapters/{claude/orchestrator.py,antigravity/adapter.py}`
- `src/relayforge/api/{schemas.py,routes/jobs.py,routes/agents.py,app.py}`
- `src/relayforge/core/agent_health.py`
- `web/src/{api.ts,pages/JobDetail.tsx,pages/Agents.tsx}`
- `tests/{unit/test_supervisor.py,unit/test_states.py,unit/test_reliability.py,integration/test_db_migrations.py,integration/test_job_reconcile.py,integration/test_jobs_api.py,integration/test_reliability_flow.py}`

## Criterios de aceptación

1. Cancelación mata el proceso y sus descendientes; integración verifica PID/árbol con psutil.
2. Timeout vence por paso, marca `TIMED_OUT` y mata el proceso.
3. Error de rate limit/red actualiza `agent_health` y lleva el Job a `WAITING_RETRY` con `retry_at`; auth/config/salida inválida no se reintentan en bucle.
4. El arranque reconcilia cualquier Job activo sin proceso como `INTERRUPTED`, mantiene estados de espera y vuelve a encolar solo Jobs listos.
5. Resume exige estado y modo válidos, persiste `resume_token`, evita la doble encolación y conserva el worktree.
6. Heartbeats persisten mientras corre un paso; salida sin avance no termina automáticamente el proceso.
7. Antigravity revisa diff y ejecuta las comprobaciones Python/web existentes más `git diff --check`.

## Límites

Las pruebas con CLIs reales, kill manual de Claude, cancelación real de Antigravity y reinicio físico de la laptop requieren el usuario/dispositivo y se registrarán como pendientes. Los tests automatizados usan procesos falsos y no invocan CLIs reales. La especificación de §25 incluye desacoplamiento de agentes al caer FastAPI; esta fase conserva la política actual de marcar como `INTERRUPTED` cualquier paso no recuperable, conforme a la alternativa permitida por POC-07.

## Resultado de verificación

- Codex: 97 passed, 1 omitida por `WinError 1314` al crear symlink; Ruff, formato, mypy, ESLint, TypeScript, 9 pruebas web, build y `git diff --check` PASS.
- Antigravity: APROBADO, 7/7 criterios, 9/9 comandos, cero denegaciones y cero cambios de fuentes; `gemini-3.8-flash-high`, esfuerzo `high`, run `4303fe39c65243b7b3c19a65b4dd7717`.
- Las pruebas manuales indicadas arriba siguen pendientes. Claude no participó ni se invocaron CLIs reales de agentes.
- Graphify incremental `graphify . --update --code-only`: 1252 nodos, 2741 aristas, 114 comunidades; 32 archivos de código reextraídos, 23 documentos omitidos por `--code-only`.
